"""Reprogramar desde el panel un turno con cobro vivo vence el cobro.

Decision del dueno (2026-09-25, misma regla que D2: simplificarle al
personal). Sintoma: reprogramar desde el panel un turno CONFIRMADO con un
link de pago del panel cancelaba el original sin tocar su cobro: el link de
Mercado Pago quedaba vivo apuntando a un turno cancelado y el turno nuevo
nacia sin cobro. Un ``pending_payment`` respondia 409 y exigia la
liberacion del admin.

Ahora la reprogramacion vence el cobro vivo del original en la MISMA
transaccion (``_expire_live_charge``: pago ``expired`` por la entidad,
``payment.preference.expire`` al outbox, sin llamada a MP) antes de
cancelarlo. El turno nuevo nace sin cobro: un confirmado sigue confirmado y
un ``pending_payment`` pasa a ``pending`` (el grafo permite
``pending_payment -> cancelled`` para el original; el nuevo es un alta).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.payments.model import Payment, PaymentStatus
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import (
    PREFERENCIA,
    _cobro,
    _con_sena,
    _confirmado_con_link,
    _espiar_invalidacion,
    _personal,
    _tienda,
    _Tienda,
    _vencimientos,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)


async def _reprogramar_y_verificar(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    t: _Tienda,
    turno: str,
    token: str,
    *,
    estado_nuevo: str,
    hora: int,
) -> None:
    invalidados = _espiar_invalidacion(monkeypatch)
    llamadas_antes = len(t.llamadas_mp)

    res = await client.patch(
        f"/appointments/{turno}/reschedule",
        headers=auth_headers(token),
        json={
            "new_starts_at": t.dia.replace(
                hour=hora, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": f"reprograma-{turno}",
        },
    )

    assert res.status_code == 200, res.text
    nuevo = res.json()["public_id"]
    assert nuevo != turno
    assert res.json()["status"] == estado_nuevo
    cobro = await _cobro(session, turno)
    cobro_estado = cobro.status
    assert cobro_estado == PaymentStatus.EXPIRED.value
    eventos = await _vencimientos(session, turno)
    assert len(eventos) == 1, eventos
    assert eventos[0].payload["preference_id"] == PREFERENCIA
    # Regla 5: ninguna llamada a MP en el request.
    assert t.llamadas_mp[llamadas_antes:] == []
    assert len(invalidados) == 1, invalidados
    session.expire_all()
    original = (
        await session.execute(select(Appointment).where(Appointment.id == turno))
    ).scalar_one()
    assert original.status == "cancelled"
    # El turno nuevo nace sin cobro.
    cobros_del_nuevo = (
        (await session.execute(select(Payment).where(Payment.appointment_id == nuevo)))
        .scalars()
        .all()
    )
    assert cobros_del_nuevo == []


@pytest.mark.asyncio
async def test_reprogramar_un_confirmado_con_link_vence_el_link(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "rp-conf", sena=False)
    token = await _personal(client, t, "staff", "rp-conf")
    turno = await _confirmado_con_link(client, t, 13)

    await _reprogramar_y_verificar(
        client,
        test_session,
        monkeypatch,
        t,
        turno,
        token,
        estado_nuevo="confirmed",
        hora=15,
    )


@pytest.mark.asyncio
async def test_reprogramar_un_pendiente_de_pago_vence_el_cobro_y_queda_pendiente(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "rp-sena", sena=True)
    token = await _personal(client, t, "staff", "rp-sena")
    turno = await _con_sena(client, t, 12)

    await _reprogramar_y_verificar(
        client,
        test_session,
        monkeypatch,
        t,
        turno,
        token,
        estado_nuevo="pending",
        hora=16,
    )


@pytest.mark.asyncio
async def test_reprogramar_sin_cobro_no_publica_vencimientos(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "rp-sin-cobro", sena=False)
    alta = await client.post(
        "/appointments/",
        headers=auth_headers(t.admin),
        json={
            "service_id": t.service,
            "staff_id": t.staff,
            "starts_at": t.dia.replace(
                hour=13, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Sin Cobro",
            "client_phone": "+5491155590013",
            "idempotency_key": "rp-sin-cobro-alta",
        },
    )
    assert alta.status_code == 201, alta.text
    turno = alta.json()["public_id"]

    res = await client.patch(
        f"/appointments/{turno}/reschedule",
        headers=auth_headers(t.admin),
        json={
            "new_starts_at": (
                t.dia.replace(hour=13, minute=0, second=0, microsecond=0)
                + timedelta(hours=2)
            ).isoformat(),
            "idempotency_key": "rp-sin-cobro-mueve",
        },
    )

    assert res.status_code == 200, res.text
    assert await _vencimientos(test_session, turno) == []
