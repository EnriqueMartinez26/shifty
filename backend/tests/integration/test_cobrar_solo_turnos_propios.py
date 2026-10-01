"""Quien cobra desde el panel: el profesional solo los turnos de su agenda.

Decision del duenio D-20260930-13 (auditoria de X8, 2026-09-30). Sintoma:
``POST /payments/preferences/{id}`` (link de pago) y
``POST /payments/{id}/manual-confirm`` (confirmacion manual) dejaban cobrar el
turno de CUALQUIER profesional a cualquier cuenta ``staff`` de la tienda, aunque
cancelar y reprogramar ya exigian ser el duenio del turno (D-20260929-03).

Ahora el admin y el superadmin cobran cualquier turno de la tienda y el
profesional solo los asignados a su ficha (``Appointment.staff_id``), con la
MISMA guarda que cancelar y reprogramar
(``appointments.guards.require_can_manage_appointment``): 403
``PERMISSION_DENIED``, antes del lock y de tocar el cobro. La recepcion sigue
sin cobrar (``_require_payment_manager``). Los listados no se acotan.

No lleva prueba de rafaga propia: la guarda lee ``staff_id`` (que no cambia
nunca) y no agrega lock ni escritura; las rafagas de estos dos endpoints viven
en ``tests/postgres/test_pg_rafaga_cobros.py``.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.payments.model import PaymentStatus
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import (
    _personal,
    _tienda,
    _Tienda,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_staff,
)
from tests.integration.test_link_del_panel_solo_turnos_vivos import _cobros


async def _otro_profesional(client: AsyncClient, t: _Tienda, slug: str) -> str:
    """Segundo profesional de la tienda, con agenda el dia de los turnos."""
    staff = await create_staff(
        client, t.admin, t.service, email=f"pro2-{slug}@example.com"
    )
    await add_staff_schedule(client, t.admin, staff, target_date=t.dia)
    return staff


async def _turno_de(client: AsyncClient, t: _Tienda, staff: str, hora: int) -> str:
    """Turno confirmado del panel (lo da de alta el admin) de ``staff``."""
    alta = await client.post(
        "/appointments/",
        headers=auth_headers(t.admin),
        json={
            "service_id": t.service,
            "staff_id": staff,
            "starts_at": t.dia.replace(
                hour=hora, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Cobro",
            "client_phone": f"+54911557{hora:05d}",
            "idempotency_key": f"cobro-propio-{t.store}-{hora}",
        },
    )
    assert alta.status_code == 201, alta.text
    return str(alta.json()["public_id"])


async def _cobrar(client: AsyncClient, via: str, turno: str, token: str) -> Response:
    if via == "link":
        return await client.post(
            f"/payments/preferences/{turno}", headers=auth_headers(token)
        )
    return await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(token), json={}
    )


def _estado_esperado(via: str) -> str:
    return (
        PaymentStatus.PENDING.value
        if via == "link"
        else PaymentStatus.MANUAL_CONFIRMED.value
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("via", ["link", "manual"])
async def test_el_profesional_cobra_los_turnos_de_su_agenda(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    via: str,
) -> None:
    slug = f"cobro-propio-{via}"
    t = await _tienda(client, monkeypatch, slug, sena=False)
    token = await _personal(client, t, "staff", slug)
    propio = await _turno_de(client, t, t.staff, 13)

    res = await _cobrar(client, via, propio, token)

    assert res.status_code == 200, res.text
    (cobro,) = await _cobros(test_session, propio)
    assert cobro.status == _estado_esperado(via)


@pytest.mark.asyncio
@pytest.mark.parametrize("estado", ["confirmed", "cancelled"])
@pytest.mark.parametrize("via", ["link", "manual"])
async def test_el_profesional_no_cobra_el_turno_de_otro(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    via: str,
    estado: str,
) -> None:
    """403 ``PERMISSION_DENIED`` sin tocar nada, tambien sobre un turno ya
    soltado: el duenio se mira ANTES del estado (no es un 409 que cuente el
    estado de un turno ajeno)."""
    slug = f"cobro-ajeno-{via}-{estado}"
    t = await _tienda(client, monkeypatch, slug, sena=False)
    token = await _personal(client, t, "staff", slug)
    otro = await _otro_profesional(client, t, slug)
    ajeno = await _turno_de(client, t, otro, 13)
    if estado != "confirmed":
        await test_session.execute(
            update(Appointment).where(Appointment.id == ajeno).values(status=estado)
        )
        await test_session.commit()
    llamadas_antes = len(t.llamadas_mp)

    res = await _cobrar(client, via, ajeno, token)

    assert res.status_code == 403, res.text
    assert res.json()["error_code"] == "PERMISSION_DENIED"
    assert await _cobros(test_session, ajeno) == []
    assert t.llamadas_mp[llamadas_antes:] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("via", ["link", "manual"])
async def test_el_admin_cobra_el_turno_de_cualquier_profesional(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    via: str,
) -> None:
    slug = f"cobro-admin-{via}"
    t = await _tienda(client, monkeypatch, slug, sena=False)
    otro = await _otro_profesional(client, t, slug)
    del_otro = await _turno_de(client, t, otro, 13)
    del_primero = await _turno_de(client, t, t.staff, 14)

    for turno in (del_otro, del_primero):
        res = await _cobrar(client, via, turno, t.admin)
        assert res.status_code == 200, res.text
        (cobro,) = await _cobros(test_session, turno)
        assert cobro.status == _estado_esperado(via)


@pytest.mark.asyncio
@pytest.mark.parametrize("via", ["link", "manual"])
async def test_la_recepcion_no_cobra_ningun_turno(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    via: str,
) -> None:
    """La guarda compartida deja pasar a la recepcion (cancelar y reprogramar
    si le tocan): el que la frena es ``_require_payment_manager``."""
    slug = f"cobro-recepcion-{via}"
    t = await _tienda(client, monkeypatch, slug, sena=False)
    token = await _personal(client, t, "receptionist", slug)
    turno = await _turno_de(client, t, t.staff, 13)

    res = await _cobrar(client, via, turno, token)

    assert res.status_code == 403, res.text
    assert res.json()["error_code"] == "PERMISSION_DENIED"
    assert await _cobros(test_session, turno) == []


@pytest.mark.asyncio
async def test_el_listado_de_turnos_no_se_acota_por_profesional(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-20260930-13: la agenda sigue mostrando todos los turnos; solo el
    cobro se acota al duenio."""
    slug = "cobro-listado"
    t = await _tienda(client, monkeypatch, slug, sena=False)
    token = await _personal(client, t, "staff", slug)
    otro = await _otro_profesional(client, t, slug)
    ajeno = await _turno_de(client, t, otro, 13)

    res = await client.get(
        "/appointments/",
        headers=auth_headers(token),
        params={"date": t.dia.date().isoformat()},
    )

    assert res.status_code == 200, res.text
    assert ajeno in {fila["public_id"] for fila in res.json()}
