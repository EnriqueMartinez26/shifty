"""El personal cancela un turno con cobro vivo y la cancelacion vence el cobro.

Decision de Mateo (2026-09-25, D2): "la idea es simplificarle al
profesional". Antes, cancelar desde el panel un turno ``pending_payment``
respondia 409 ``PAYMENT_APPOINTMENT_REQUIRES_RELEASE`` y exigia la liberacion,
que es solo del admin: el profesional dependia del dueno. Y un turno
CONFIRMADO con un link generado desde el panel se cancelaba dejando el link
de Mercado Pago vivo.

Ahora cualquier rol del personal que ya podia cancelar (admin, recepcion,
profesional: ``PATCH /appointments/{id}/cancel`` pide solo sesion de la
tienda) cancela un turno con cobro vivo y, en la MISMA transaccion, vence el
cobro por la entidad (``Payment.apply_status``) y publica
``payment.preference.expire`` para que el outbox venza el link en MP despues,
sin lock (regla 5). Orden de locks turno -> pago (regla 7). La
disponibilidad se invalida despues del commit. Un turno con el pago ya
acreditado se cancela como siempre y su pago queda acreditado (fuera de D2).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.appointments.service as appointments_service
from core.availability_cache import invalidate_availability
import modules.payments.service as payments_service
from modules.appointments.model import Appointment
from modules.payments.model import OutboxMessage, Payment, PaymentStatus
from modules.payments.service import EVENT_PREFERENCE_EXPIRE
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

PREFERENCIA = "pref-d2-cancel"


class _Tienda:
    def __init__(self, store: str, admin: str, service: str, staff: str) -> None:
        self.store = store
        self.admin = admin
        self.service = service
        self.staff = staff
        self.dia = datetime.now(timezone.utc) + timedelta(days=4)
        self.llamadas_mp: list[tuple[str, str]] = []


async def _tienda(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, slug: str, *, sena: bool
) -> _Tienda:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    llamadas: list[tuple[str, str]] = []

    async def mp(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        llamadas.append((method, path))
        return {
            "id": PREFERENCIA,
            "init_point": f"https://www.mercadopago.com/checkout?pref={slug}",
        }

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    for url, cuerpo in (
        ("/stores/me/feature-flags", {"payments": True}),
        ("/payments/gateway-config", {"access_token": "TEST-D2-TOKEN"}),
    ):
        res = await client.put(url, headers=auth_headers(token), json=cuerpo)
        assert res.status_code == 200, res.text
    service = (
        await create_service(
            client,
            token,
            deposit_mode="required",
            deposit_type="fixed",
            deposit_amount=2500,
        )
        if sena
        else await create_service(client, token)
    )
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    t = _Tienda(store, token, service, staff)
    t.llamadas_mp = llamadas
    await add_staff_schedule(client, token, staff, target_date=t.dia)
    return t


async def _personal(client: AsyncClient, t: _Tienda, rol: str, slug: str) -> str:
    """Token de un usuario del personal con ``rol`` (staff = profesional)."""
    email = f"{rol}-{slug}@example.com"
    alta = await client.post(
        "/users/",
        headers=auth_headers(t.admin),
        json={
            "email": email,
            "password": "Password123!",
            "first_name": "Persona",
            "last_name": rol.title(),
            "role": rol,
        },
    )
    assert alta.status_code == 201, alta.text
    login = await client.post(
        "/auth/login", json={"email": email, "password": "Password123!"}
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


async def _confirmado_con_link(client: AsyncClient, t: _Tienda, hora: int) -> str:
    """Turno confirmado del panel y, encima, el link de pago del panel."""
    alta = await client.post(
        "/appointments/",
        headers=auth_headers(t.admin),
        json={
            "service_id": t.service,
            "staff_id": t.staff,
            "starts_at": t.dia.replace(
                hour=hora, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Panel",
            "client_phone": f"+54911555{hora:05d}",
            "idempotency_key": f"d2-alta-{t.store}-{hora}",
        },
    )
    assert alta.status_code == 201, alta.text
    assert alta.json()["status"] == "confirmed"
    turno = str(alta.json()["public_id"])
    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert link.status_code == 200, link.text
    return turno


async def _con_sena(client: AsyncClient, t: _Tienda, hora: int) -> str:
    """Reserva publica con sena: nace ``pending_payment`` con su cobro."""
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": t.store,
            "service_id": t.service,
            "staff_id": t.staff,
            "starts_at": t.dia.replace(
                hour=hora, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Sena",
            "client_phone": f"+54911556{hora:05d}",
            "accepts_terms": True,
            "payment_method": "mercadopago",
            "idempotency_key": f"d2-sena-{t.store}-{hora}",
        },
    )
    assert reserva.status_code == 201, reserva.text
    assert reserva.json()["status"] == "pending_payment"
    return str(reserva.json()["public_id"])


def _espiar_invalidacion(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    invalidados: list[str] = []
    # El service la importa por nombre: se espia en su modulo.
    original = invalidate_availability

    async def espia(cache: Any, store_id: str, *dias: datetime) -> None:
        invalidados.append(store_id)
        await original(cache, store_id, *dias)

    monkeypatch.setattr(appointments_service, "invalidate_availability", espia)
    return invalidados


async def _cobro(session: AsyncSession, turno: str) -> Payment:
    session.expire_all()
    return (
        await session.execute(select(Payment).where(Payment.appointment_id == turno))
    ).scalar_one()


async def _vencimientos(session: AsyncSession, turno: str) -> list[OutboxMessage]:
    session.expire_all()
    filas = (
        await session.execute(
            select(OutboxMessage).where(
                OutboxMessage.event_type == EVENT_PREFERENCE_EXPIRE
            )
        )
    ).scalars()
    return [f for f in filas if f.payload.get("appointment_id") == turno]


async def _cancelar_y_verificar(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    t: _Tienda,
    turno: str,
    token: str,
) -> None:
    invalidados = _espiar_invalidacion(monkeypatch)
    llamadas_antes = len(t.llamadas_mp)

    res = await client.patch(
        f"/appointments/{turno}/cancel", headers=auth_headers(token)
    )

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"
    cobro = await _cobro(session, turno)
    cobro_id, cobro_estado = cobro.id, cobro.status
    assert cobro_estado == PaymentStatus.EXPIRED.value
    eventos = await _vencimientos(session, turno)
    assert len(eventos) == 1, eventos
    assert eventos[0].payload["preference_id"] == PREFERENCIA
    assert eventos[0].payload["payment_id"] == cobro_id
    assert eventos[0].processed_at is None
    # Regla 5: ninguna llamada a MP en el request; la hace el outbox.
    assert t.llamadas_mp[llamadas_antes:] == []
    assert len(invalidados) == 1, invalidados
    session.expire_all()
    quedo = (
        await session.execute(select(Appointment).where(Appointment.id == turno))
    ).scalar_one()
    assert quedo.status == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["staff", "receptionist"])
async def test_el_personal_cancela_un_confirmado_con_link_y_el_link_se_vence(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    rol: str,
) -> None:
    t = await _tienda(client, monkeypatch, f"d2-conf-{rol}", sena=False)
    token = await _personal(client, t, rol, f"d2-conf-{rol}")
    turno = await _confirmado_con_link(client, t, 13)

    await _cancelar_y_verificar(client, test_session, monkeypatch, t, turno, token)


@pytest.mark.asyncio
async def test_el_profesional_cancela_un_pendiente_de_pago_y_el_cobro_se_vence(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "d2-sena", sena=True)
    token = await _personal(client, t, "staff", "d2-sena")
    turno = await _con_sena(client, t, 12)

    await _cancelar_y_verificar(client, test_session, monkeypatch, t, turno, token)


@pytest.mark.asyncio
async def test_un_intento_rechazado_tambien_se_vence_al_cancelar(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revision de perf/f4-pay (2026-09-25): tras un rechazo el link de MP
    sigue pagable, asi que ``rejected`` es cobro vivo y la cancelacion lo
    vence por la entidad (``rejected -> expired`` esta en el grafo)."""
    t = await _tienda(client, monkeypatch, "d2-rechazado", sena=False)
    token = await _personal(client, t, "staff", "d2-rechazado")
    turno = await _confirmado_con_link(client, t, 15)
    cobro = await _cobro(test_session, turno)
    assert cobro.apply_status(PaymentStatus.REJECTED.value)
    await test_session.commit()

    await _cancelar_y_verificar(client, test_session, monkeypatch, t, turno, token)


@pytest.mark.asyncio
async def test_un_turno_pagado_se_cancela_como_antes_y_el_pago_queda_acreditado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fuera de D2: cancelar un turno con la sena acreditada no toca el pago
    (la devolucion la decide la tienda, como hasta hoy)."""
    t = await _tienda(client, monkeypatch, "d2-pagado", sena=False)
    token = await _personal(client, t, "staff", "d2-pagado")
    turno = await _confirmado_con_link(client, t, 14)
    cobro = await _cobro(test_session, turno)
    cobro.apply_status(PaymentStatus.APPROVED.value)
    await test_session.commit()

    res = await client.patch(
        f"/appointments/{turno}/cancel", headers=auth_headers(token)
    )

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"
    assert (await _cobro(test_session, turno)).status == PaymentStatus.APPROVED.value
    assert await _vencimientos(test_session, turno) == []


@pytest.mark.asyncio
async def test_liberar_sigue_siendo_solo_del_admin_y_funciona_igual(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "d2-liberar", sena=True)
    token = await _personal(client, t, "staff", "d2-liberar")
    turno = await _con_sena(client, t, 15)

    del_profesional = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(token)
    )
    del_admin = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(t.admin)
    )

    assert del_profesional.status_code == 403, del_profesional.text
    assert del_admin.status_code == 200, del_admin.text
    assert del_admin.json()["status"] == "expired"
    assert (await _cobro(test_session, turno)).status == PaymentStatus.EXPIRED.value
    assert len(await _vencimientos(test_session, turno)) == 1


@pytest.mark.asyncio
async def test_un_cobro_con_link_placeholder_se_vence_sin_publicar_nada(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revision de perf/f4-pay (2026-09-25, #6): un placeholder no existe en
    Mercado Pago. El cobro se vence igual, pero sin ``payment.preference.expire``
    (mismo criterio que ``_expire_live_checkout`` y ``_discard_unsealed_link``)."""
    t = await _tienda(client, monkeypatch, "d2-placeholder", sena=False)
    turno = await _confirmado_con_link(client, t, 16)
    cobro = await _cobro(test_session, turno)
    cobro.preference_id, cobro.payment_link = payments_service._placeholder_link(turno)
    await test_session.commit()

    res = await client.patch(
        f"/appointments/{turno}/cancel", headers=auth_headers(t.admin)
    )

    assert res.status_code == 200, res.text
    assert (await _cobro(test_session, turno)).status == PaymentStatus.EXPIRED.value
    assert await _vencimientos(test_session, turno) == []
