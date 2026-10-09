"""Un turno con un resto vivo no se reprograma (D-20261008-01).

Revision de la PR #137 (W2, 2026-10-08). Reprogramar desde el panel cancela el
original y crea un turno nuevo sin cobro: el resto registrado quedaba colgado
del cancelado (contando como ingreso) y el turno nuevo volvia a pedir el
precio entero. Ahora el panel responde 409 ``REMAINDER_RESCHEDULE_DENIED``
bajo el lock del turno y antes de tocar nada, como
``DEPOSIT_PENDING_RESCHEDULE_DENIED``: se revierte el resto o se cancela.

El cliente ya no reprograma un turno con pago acreditado
(``PAID_APPOINTMENT_RESCHEDULE_DENIED``); con la sena devuelta y el resto
vivo, el turno sigue pagado para esa guarda y para el historial.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import local_to_utc
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import Payment, PaymentStatus
from modules.public_api.repository import PublicRepository
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _Semilla, _tienda


async def _turno_con_resto(
    client: AsyncClient, session: AsyncSession, slug: str
) -> tuple[str, str]:
    token, store, staff, servicio = await _tienda(client, session, slug)
    semilla = _Semilla(session, store, staff)
    ana = semilla.cliente("Ana", "Reprograma")
    await session.commit()
    turno = await semilla.turno(
        f"{slug}-1",
        date(2026, 10, 20),
        time(10, 0),
        servicio,
        ana,
        AppointmentStatus.CONFIRMED,
        precio=Decimal("3200"),
        pago=(Decimal("960"), PaymentStatus.APPROVED),
    )
    res = await client.post(
        f"/payments/{turno}/remaining-payment",
        headers=auth_headers(token),
        json={"idempotency_key": f"{slug}-resto-0001"},
    )
    assert res.status_code == 201, res.text
    return token, turno


async def _reprogramar(
    client: AsyncClient, token: str, turno: str, clave: str
) -> Response:
    return await client.patch(
        f"/appointments/{turno}/reschedule",
        headers=auth_headers(token),
        json={
            "new_starts_at": local_to_utc(date(2026, 10, 21), time(11, 0)).isoformat(),
            "idempotency_key": clave,
            "allow_outside_schedule": True,
        },
    )


@pytest.mark.asyncio
async def test_el_panel_no_reprograma_un_turno_con_resto_vivo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, turno = await _turno_con_resto(client, test_session, "repro-resto")

    res = await _reprogramar(client, token, turno, "repro-resto-clave-1")

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "REMAINDER_RESCHEDULE_DENIED"
    test_session.expire_all()
    turnos = (await test_session.execute(select(Appointment))).scalars().all()
    assert [t.status for t in turnos] == [AppointmentStatus.CONFIRMED.value]


@pytest.mark.asyncio
async def test_revertido_el_resto_el_panel_reprograma(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, turno = await _turno_con_resto(client, test_session, "repro-revert")
    revertido = await client.post(
        f"/payments/{turno}/remaining-payment/revert", headers=auth_headers(token)
    )
    assert revertido.status_code == 200, revertido.text

    res = await _reprogramar(client, token, turno, "repro-revert-clave-1")

    assert res.status_code == 200, res.text


async def _sena_devuelta(session: AsyncSession, turno: str) -> None:
    session.expire_all()
    cobro = (
        await session.execute(select(Payment).where(Payment.appointment_id == turno))
    ).scalar_one()
    assert cobro.apply_status(PaymentStatus.REFUNDED.value)
    await session.commit()


@pytest.mark.asyncio
async def test_para_el_cliente_un_resto_vivo_es_un_turno_pagado(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Con la sena devuelta, el resto vivo sigue frenando la reprogramacion
    del cliente (``paid_appointment_ids``) y el historial no la ofrece."""
    _, turno = await _turno_con_resto(client, test_session, "repro-cliente")
    await _sena_devuelta(test_session, turno)
    repo = PublicRepository(test_session)

    assert await repo.paid_appointment_ids([turno]) == {turno}

    fila = await test_session.execute(
        text("select client_id, store_id from appointments where id = :t"),
        {"t": turno},
    )
    client_id, store_id = fila.one()
    historial = await repo.get_client_appointments(client_id, store_id, limit=5)
    assert [(a.id, pagado) for a, pagado, _ in historial] == [(turno, True)]


@pytest.mark.asyncio
async def test_sin_cobro_ni_resto_el_turno_no_esta_pagado(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, turno = await _turno_con_resto(client, test_session, "repro-sin")
    # Resto revertido y sena devuelta: no queda nada pagado.
    await test_session.execute(
        text(
            "update appointment_balance_payments set reverted_at = created_at, "
            "reverted_by = recorded_by where appointment_id = :t"
        ),
        {"t": turno},
    )
    await test_session.commit()
    await _sena_devuelta(test_session, turno)

    assert await PublicRepository(test_session).paid_appointment_ids([turno]) == set()
