"""Reprogramar desde el panel un turno con cobro vivo vence el cobro.

Decision del dueno (2026-09-25, misma regla que D2: simplificarle al
personal). Sintoma: reprogramar desde el panel un turno CONFIRMADO con un
link de pago del panel cancelaba el original sin tocar su cobro: el link de
Mercado Pago quedaba vivo apuntando a un turno cancelado y el turno nuevo
nacia sin cobro. Un ``pending_payment`` respondia 409 y exigia la
liberacion del admin.

Ahora la reprogramacion vence el cobro vivo del original en la MISMA
transaccion (``expire_live_charge``: pago ``expired`` por la entidad,
``payment.preference.expire`` al outbox, sin llamada a MP) antes de
cancelarlo. El turno nuevo nace sin cobro y un confirmado sigue confirmado.

Un turno en ``pending_payment`` (sena REQUERIDA pendiente) no se reprograma
desde el panel: 409 ``DEPOSIT_PENDING_RESCHEDULE_DENIED`` ("Cobrá la seña o
cancelá el turno antes de moverlo"), sin tocar nada (decision del dueno
2026-09-25: opcion A). Reprogramarlo como ``pending`` sin cobro, lo que se
hizo mientras tanto, perdia la sena requerida. El personal lo puede cancelar
(D2 vence el cobro) o cobrar la sena y despues moverlo. El link del panel de
un turno CONFIRMADO no es una sena requerida: ese sigue reprogramandose y
vence el link.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.payments.model import OutboxMessage, Payment, PaymentStatus
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
@pytest.mark.parametrize("rol", ["admin", "staff"])
async def test_reprogramar_un_pendiente_de_pago_es_409_y_no_toca_nada(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    rol: str,
) -> None:
    t = await _tienda(client, monkeypatch, f"rp-sena-{rol}", sena=True)
    token = t.admin if rol == "admin" else await _personal(client, t, rol, "rp-sena")
    turno = await _con_sena(client, t, 12)
    cobro = await _cobro(test_session, turno)
    antes = (cobro.status, cobro.preference_id, cobro.version, cobro.amount)
    turnos_antes = await _cantidad(test_session, Appointment)
    eventos_antes = await _cantidad(test_session, OutboxMessage)
    invalidados = _espiar_invalidacion(monkeypatch)
    llamadas_antes = len(t.llamadas_mp)

    res = await client.patch(
        f"/appointments/{turno}/reschedule",
        headers=auth_headers(token),
        json={
            "new_starts_at": t.dia.replace(
                hour=16, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": f"reprograma-sena-{rol}",
        },
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "DEPOSIT_PENDING_RESCHEDULE_DENIED"
    assert res.json()["message"] == "Cobrá la seña o cancelá el turno antes de moverlo"
    # Nada cambio: la sena sigue pendiente con su link, el turno igual.
    cobro = await _cobro(test_session, turno)
    assert (cobro.status, cobro.preference_id, cobro.version, cobro.amount) == antes
    assert antes[0] == PaymentStatus.PENDING.value
    test_session.expire_all()
    original = (
        await test_session.execute(select(Appointment).where(Appointment.id == turno))
    ).scalar_one()
    assert original.status == "pending_payment"
    assert await _cantidad(test_session, Appointment) == turnos_antes
    assert await _cantidad(test_session, OutboxMessage) == eventos_antes
    assert await _vencimientos(test_session, turno) == []
    assert invalidados == []
    assert t.llamadas_mp[llamadas_antes:] == []

    # Cancelar sigue permitido y vence el cobro (D2).
    cancelado = await client.patch(
        f"/appointments/{turno}/cancel", headers=auth_headers(token)
    )
    assert cancelado.status_code == 200, cancelado.text
    assert (await _cobro(test_session, turno)).status == PaymentStatus.EXPIRED.value


async def _cantidad(session: AsyncSession, modelo: Any) -> int:
    session.expire_all()
    return int(
        (await session.execute(select(func.count()).select_from(modelo))).scalar_one()
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
