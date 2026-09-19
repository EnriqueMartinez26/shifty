"""Un pago aprobado que llega despues de liberar el turno no se disfraza de confirmacion.

2026-09-19, S-16 (hueco preexistente que B1-04 agranda): el webhook de un
pago aprobado sobre un turno ya liberado (EXPIRED por la retencion vencida)
se aplicaba -- el grafo del pago permite expired -> approved --, pero
``sync_appointment_with_payment`` no toca un turno EXPIRED y el outbox
publicaba ``payment.approved``: el dueno leia "Seña acreditada ... El turno
quedo confirmado automaticamente" (falso) y el cliente recibia el mail de
"turno confirmado" de un turno que ya no existia.

Decision del coordinador: el pago SI queda acreditado (la plata entro y hay
que poder devolverla o reasignarla), el turno NO se revive (su horario pudo
tomarlo otra persona), el aviso al dueno dice la verdad con su propio tipo, y
el cliente no recibe el mail de "turno confirmado".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.jobs as jobs
from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import Notification, NotificationType
from modules.payments.jobs import expire_unpaid_appointments, process_outbox_batch
from modules.payments.model import Payment, PaymentStatus
from modules.payments.processing import apply_mercadopago_webhook_payload
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _approved_remote_payment,
    _book_with_mercadopago,
    _configure_gateway,
    _enable_payments,
    _stub_mercadopago,
)


# Tipo propio del aviso (literal a proposito: es el contrato del panel).
EVENTO_PAGO_SOBRE_TURNO_LIBERADO = "payment.received_on_released_appointment"


def _espiar_confirmaciones(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    enviadas: list[str | None] = []

    async def confirmacion(*, email: str | None, details: dict[str, Any]) -> None:
        enviadas.append(details.get("public_id"))

    monkeypatch.setattr(jobs, "send_confirmation_email", confirmacion)
    return enviadas


async def _turno_con_sena(
    client: AsyncClient, session: AsyncSession, slug: str, hour: int
) -> tuple[Appointment, Payment]:
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno_id = await _book_with_mercadopago(
        client, token, store, slug_suffix=slug, hour=hour
    )
    turno = (
        await session.execute(select(Appointment).where(Appointment.id == turno_id))
    ).scalar_one()
    pago = (
        await session.execute(select(Payment).where(Payment.appointment_id == turno_id))
    ).scalar_one()
    return turno, pago


async def _webhook_aprobado(session: AsyncSession, pago: Payment) -> None:
    remoto = _approved_remote_payment(pago)
    assert await apply_mercadopago_webhook_payload(
        session, store_id=pago.store_id, payload={"data": remoto, "status": "approved"}
    )
    await session.commit()


async def _avisos(session: AsyncSession, appointment_id: str) -> list[Notification]:
    return list(
        (
            await session.execute(
                select(Notification).where(
                    Notification.appointment_id == appointment_id
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_pago_aprobado_sobre_turno_liberado_se_acredita_sin_revivir_el_turno(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    confirmaciones = _espiar_confirmaciones(monkeypatch)
    turno, pago = await _turno_con_sena(client, test_session, "s16-liberado", 10)

    # La retencion vence y el job libera el turno (MP todavia no sabe nada).
    await test_session.execute(
        update(Appointment)
        .where(Appointment.id == turno.id)
        .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    )
    await test_session.commit()
    assert (await expire_unpaid_appointments(test_session))["expired"] == 1

    # Despues llega el webhook: el cliente pago igual.
    await _webhook_aprobado(test_session, pago)
    await process_outbox_batch(test_session)

    await test_session.refresh(turno)
    await test_session.refresh(pago)
    assert pago.status == PaymentStatus.APPROVED.value, "la plata entro"
    assert turno.status == AppointmentStatus.EXPIRED.value, "el turno no revive"
    avisos = await _avisos(test_session, turno.id)
    assert [a.type for a in avisos] == [EVENTO_PAGO_SOBRE_TURNO_LIBERADO]
    assert (
        NotificationType.PAYMENT_ON_RELEASED_APPOINTMENT.value
        == EVENTO_PAGO_SOBRE_TURNO_LIBERADO
    )
    aviso = avisos[0]
    assert "confirmado" not in (aviso.body or "")
    assert "ya liberado" in aviso.title.lower() or "ya liberado" in (aviso.body or "")
    assert "reembolso" in (aviso.body or "") and "reasign" in (aviso.body or "")
    assert confirmaciones == [], "el cliente no recibe 'turno confirmado'"


@pytest.mark.asyncio
async def test_pago_aprobado_sobre_turno_pendiente_sigue_confirmando(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    confirmaciones = _espiar_confirmaciones(monkeypatch)
    turno, pago = await _turno_con_sena(client, test_session, "s16-normal", 11)

    await _webhook_aprobado(test_session, pago)
    await process_outbox_batch(test_session)

    await test_session.refresh(turno)
    assert turno.status == AppointmentStatus.CONFIRMED.value
    avisos = await _avisos(test_session, turno.id)
    assert [a.type for a in avisos] == [NotificationType.PAYMENT_APPROVED.value]
    assert "confirmado automaticamente" in (avisos[0].body or "")
    assert confirmaciones == [turno.id]
