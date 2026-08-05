from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import Notification, NotificationType
from modules.payments.model import (
    OutboxMessage,
    Payment,
    PaymentGatewayConfig,
    PaymentStatus,
    WebhookInbox,
)
from modules.payments.processing import (
    apply_mercadopago_webhook_payload,
    enrich_mercadopago_webhook_payload,
)
from modules.payments.service import (
    fetch_mercadopago_payment,
    search_mercadopago_payments,
)

# Ventana hacia atras que revisa la conciliacion. Mas alla de esto un pago
# pendiente ya se considera abandonado.
RECONCILIATION_LOOKBACK_DAYS = 30


async def process_outbox_batch(
    db: AsyncSession,
    *,
    limit: int = 100,
    store_id: str | None = None,
) -> dict[str, int]:
    filters: list[ColumnElement[bool]] = [
        OutboxMessage.processed_at.is_(None),
        OutboxMessage.is_active.is_(True),
    ]
    if store_id:
        filters.append(OutboxMessage.store_id == store_id)

    result = await db.execute(
        select(OutboxMessage)
        .where(*filters)
        .order_by(OutboxMessage.created_at.asc())
        .limit(limit)
    )
    messages = list(result.scalars().all())
    now = datetime.now(timezone.utc)
    processed = 0
    failed = 0

    for message in messages:
        try:
            notification = _build_store_notification(message)
            if notification is not None:
                db.add(notification)
            message.processed_at = now
            message.error = None
            processed += 1
        except Exception as exc:
            message.error = str(exc)[:1000]
            failed += 1

    await db.commit()
    return {"processed": processed, "failed": failed, "inspected": len(messages)}


def _build_store_notification(message: OutboxMessage) -> Notification | None:
    """Traduce un evento del outbox en una notificacion para el panel de la tienda.

    Los eventos que no le aportan nada al dueño (por ejemplo, la creacion del link
    de pago) se consumen sin generar ruido en la campanita.
    """
    if not message.store_id:
        return None

    payload = message.payload if isinstance(message.payload, dict) else {}
    appointment_id = payload.get("appointment_id")
    client_name = str(payload.get("client_name") or "Un cliente")
    service_name = str(payload.get("service_name") or "un servicio")

    if message.event_type == NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value:
        return Notification(
            store_id=message.store_id,
            type=message.event_type,
            title="Turno pendiente de confirmar",
            body=(
                f"{client_name} reservo {service_name} y va a coordinar el pago. "
                "Confirmalo cuando recibas la transferencia."
            ),
            appointment_id=str(appointment_id) if appointment_id else None,
        )

    if message.event_type == NotificationType.PAYMENT_APPROVED.value:
        amount = payload.get("amount")
        amount_label = f" de ${amount}" if amount else ""
        return Notification(
            store_id=message.store_id,
            type=message.event_type,
            title="Seña acreditada",
            body=(
                f"{client_name} pago la seña{amount_label} de {service_name}. "
                "El turno quedo confirmado automaticamente."
            ),
            appointment_id=str(appointment_id) if appointment_id else None,
        )

    return None


async def process_webhook_inbox_batch(
    db: AsyncSession,
    *,
    limit: int = 100,
    store_id: str | None = None,
) -> dict[str, int]:
    filters: list[ColumnElement[bool]] = [
        WebhookInbox.processed_at.is_(None),
        WebhookInbox.is_active.is_(True),
    ]
    if store_id:
        filters.append(WebhookInbox.store_id == store_id)

    result = await db.execute(
        select(WebhookInbox)
        .where(*filters)
        .order_by(WebhookInbox.created_at.asc())
        .limit(limit)
    )
    inbox_items = list(result.scalars().all())
    processed = 0
    failed = 0

    for inbox in inbox_items:
        try:
            applied = True
            if inbox.provider == "mercadopago" and inbox.store_id:
                inbox.payload = await enrich_mercadopago_webhook_payload(
                    db, store_id=inbox.store_id, payload=inbox.payload
                )
                applied = await apply_mercadopago_webhook_payload(
                    db, store_id=inbox.store_id, payload=inbox.payload
                )
            if applied:
                inbox.mark_processed()
                processed += 1
            else:
                inbox.register_failure("No se pudo resolver el pago del webhook")
                failed += 1
        except Exception as exc:
            inbox.register_failure(str(exc))
            failed += 1

    await db.commit()
    return {"processed": processed, "failed": failed, "inspected": len(inbox_items)}


async def reconcile_pending_payments(
    db: AsyncSession, *, limit: int = 100
) -> dict[str, int]:
    """Consulta a Mercado Pago los cobros que siguen pendientes en Shifty.

    Es la red de contencion del webhook: si la notificacion nunca llego, llego
    sin firma valida o no pudimos resolverla, aca recuperamos el estado real
    preguntandole directamente a Mercado Pago.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECONCILIATION_LOOKBACK_DAYS)
    result = await db.execute(
        select(Payment)
        .join(
            PaymentGatewayConfig,
            PaymentGatewayConfig.store_id == Payment.store_id,
        )
        .where(
            Payment.status == PaymentStatus.PENDING.value,
            Payment.provider == "mercadopago",
            Payment.is_active.is_(True),
            Payment.created_at >= cutoff,
            PaymentGatewayConfig.provider == "mercadopago",
        )
        .order_by(Payment.created_at.asc())
        .limit(limit)
    )
    payments = list(result.scalars().all())

    reconciled = 0
    failed = 0
    for payment in payments:
        try:
            remote = await _fetch_remote_payment(db, payment)
            if not remote:
                continue
            applied = await apply_mercadopago_webhook_payload(
                db,
                store_id=payment.store_id,
                payload={"data": remote, "status": remote.get("status")},
            )
            if applied:
                reconciled += 1
        except Exception:
            # Un pago que no se puede conciliar no debe frenar al resto del lote.
            failed += 1

    await db.commit()
    return {"reconciled": reconciled, "failed": failed, "inspected": len(payments)}


async def _fetch_remote_payment(
    db: AsyncSession, payment: Payment
) -> dict[str, Any] | None:
    if payment.external_payment_id:
        return await fetch_mercadopago_payment(
            db,
            store_id=payment.store_id,
            payment_id=payment.external_payment_id,
        )

    candidates = await search_mercadopago_payments(
        db,
        store_id=payment.store_id,
        external_reference=payment.appointment_id,
    )
    if not candidates:
        return None
    # Nos quedamos con un cobro acreditado si existe; si no, con el mas reciente.
    for candidate in candidates:
        if str(candidate.get("status") or "").lower() == "approved":
            return candidate
    return candidates[0]


async def expire_unpaid_appointments(
    db: AsyncSession, *, limit: int = 100
) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Appointment, Payment)
        .outerjoin(Payment, Payment.appointment_id == Appointment.id)
        .where(
            Appointment.status.in_(
                [
                    AppointmentStatus.PENDING.value,
                    AppointmentStatus.PENDING_PAYMENT.value,
                ]
            ),
            Appointment.expires_at.is_not(None),
            Appointment.expires_at <= now,
            or_(Payment.id.is_(None), Payment.status == PaymentStatus.PENDING.value),
        )
        .order_by(Appointment.expires_at.asc())
        .limit(limit)
        # Postgres rechaza FOR UPDATE sobre el lado nullable de un OUTER JOIN,
        # asi que bloqueamos solo la fila del turno.
        .with_for_update(skip_locked=True, of=Appointment)
    )
    rows = list(result.all())
    expired = 0
    rescued = 0
    for appointment, payment in rows:
        # Ultimo chequeo antes de liberar el turno: si el cobro se acredito y el
        # webhook nunca llego, vencerlo perderia una reserva ya pagada.
        if payment and await _payment_was_accredited(db, payment):
            rescued += 1
            continue
        appointment.apply_status_transition(AppointmentStatus.EXPIRED)
        if payment:
            payment.status = PaymentStatus.EXPIRED.value
        expired += 1
    await db.commit()
    return {"expired": expired, "rescued": rescued, "inspected": len(rows)}


async def _payment_was_accredited(db: AsyncSession, payment: Payment) -> bool:
    """Verifica contra Mercado Pago si un cobro pendiente ya fue acreditado."""
    if payment.provider != "mercadopago":
        return False
    try:
        remote = await _fetch_remote_payment(db, payment)
    except Exception:
        # Si no podemos preguntar, dejamos que el turno venza: la conciliacion
        # posterior va a detectar el cobro y dejarlo visible para reembolso.
        return False
    if not remote:
        return False
    applied = await apply_mercadopago_webhook_payload(
        db,
        store_id=payment.store_id,
        payload={"data": remote, "status": remote.get("status")},
    )
    return applied and payment.status in {
        PaymentStatus.APPROVED.value,
        PaymentStatus.MANUAL_CONFIRMED.value,
    }
