"""Un cobro rechazado es vivo: los caminos automaticos que sueltan el turno lo vencen.

Revision de perf/f4-pay (2026-09-25, #3). ``LIVE_CHARGE_PAYMENT_STATUSES``
incluye ``rejected`` (MP deja reintentar sobre el mismo link), pero:

- el webhook que rechaza el cobro de un ``pending_payment`` pasaba el turno a
  ``expired`` (``sync_appointment_with_payment``) sin vencer el cobro ni
  publicar ``payment.preference.expire``: quedaba un link vivo sobre un turno
  vencido. Ahora, cuando el turno sale de los estados cobrables por el pago,
  el cobro se vence con el camino compartido (``expire_live_charge``).
- el job de retenciones vencidas (``_expired_holds_query``) solo tomaba cobros
  ``pending``: un turno PENDIENTE cuyo link se rechazo no se liberaba nunca, y
  el cliente tampoco podia cancelarlo (cobro vivo). Ahora toma los estados de
  ``LIVE_CHARGE_PAYMENT_STATUSES``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.payments.jobs import expire_unpaid_appointments
from modules.payments.model import Payment, PaymentStatus
from modules.payments.processing import apply_mercadopago_webhook_payload
from tests.integration.test_autogestion_permisos_por_estado import _turno_en_estado
from tests.integration.test_caracterizacion_autogestion import _con_turno
from tests.integration.test_release_sin_mp_bajo_lock import (
    _evento,
    _MercadoPago,
    _turno_con_cobro,
)


async def _turno(session: AsyncSession, turno_id: str) -> Appointment:
    session.expire_all()
    return (
        await session.execute(select(Appointment).where(Appointment.id == turno_id))
    ).scalar_one()


async def _pago(session: AsyncSession, turno_id: str) -> Payment:
    session.expire_all()
    return (
        await session.execute(select(Payment).where(Payment.appointment_id == turno_id))
    ).scalar_one()


@pytest.mark.asyncio
async def test_el_webhook_que_rechaza_un_pending_payment_vence_el_cobro(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    mp = _MercadoPago(test_session)
    _token, turno = await _turno_con_cobro(client, monkeypatch, mp, "rechazo-webhook")
    pago = await _pago(test_session, turno)
    store_id, importe = pago.store_id, float(pago.amount)
    referencia = pago.current_external_reference

    aplicado = await apply_mercadopago_webhook_payload(
        test_session,
        store_id=store_id,
        payload={
            "status": "rejected",
            "data": {
                "id": "mp-rechazo-1",
                "status": "rejected",
                "external_reference": referencia,
                "preference_id": "pref-release-b104",
                "transaction_amount": importe,
                "currency_id": "ARS",
            },
        },
    )
    await test_session.commit()

    assert aplicado is True
    assert (await _turno(test_session, turno)).status == "expired"
    assert (await _pago(test_session, turno)).status == PaymentStatus.EXPIRED.value
    evento = await _evento(test_session)
    assert evento.payload["preference_id"] == "pref-release-b104"
    assert evento.processed_at is None


@pytest.mark.asyncio
async def test_el_job_suelta_un_turno_pendiente_con_el_link_rechazado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _t, base = await _con_turno(client, monkeypatch, "rechazo-job")
    turno = await _turno_en_estado(test_session, base, "pending")
    await test_session.execute(
        update(Appointment)
        .where(Appointment.id == turno)
        .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    )
    base_turno = await _turno(test_session, turno)
    test_session.add(
        Payment(
            store_id=base_turno.store_id,
            appointment_id=turno,
            amount=Decimal("2500"),
            status=PaymentStatus.REJECTED.value,
            # Sin consulta a MP en la fase A (solo se preguntan los de MP).
            provider="manual",
        )
    )
    await test_session.commit()

    resultado = await expire_unpaid_appointments(test_session)

    assert resultado["expired"] >= 1, resultado
    assert (await _turno(test_session, turno)).status == "expired"
    assert (await _pago(test_session, turno)).status == PaymentStatus.EXPIRED.value
