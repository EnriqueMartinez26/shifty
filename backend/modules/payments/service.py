from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import OutboxMessage, Payment, PaymentStatus
from modules.services.model import Service


ACTIVE_APPOINTMENT_STATUSES = {
    AppointmentStatus.PENDING.value,
    AppointmentStatus.PENDING_PAYMENT.value,
    AppointmentStatus.CONFIRMED.value,
}


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_service_payment_amount(service: Service) -> Decimal:
    mode = getattr(service, "deposit_mode", "none") or "none"
    payment_type = getattr(service, "deposit_type", "percent") or "percent"
    raw_amount = getattr(service, "deposit_amount", None)
    service_price = _money(Decimal(str(service.price or 0)))

    if mode == "none":
        return Decimal("0.00")

    if payment_type == "full":
        return service_price

    if raw_amount is None:
        return Decimal("0.00")

    configured_amount = _money(Decimal(str(raw_amount)))
    if payment_type == "fixed":
        return min(configured_amount, service_price)
    if payment_type == "percent":
        return _money(service_price * configured_amount / Decimal("100"))
    return Decimal("0.00")


def service_requires_payment(service: Service) -> bool:
    mode = getattr(service, "deposit_mode", "none") or "none"
    return mode != "none" and calculate_service_payment_amount(service) > 0


async def ensure_payment_preference(
    db: AsyncSession,
    *,
    appointment: Appointment,
    service: Service,
    store_id: str,
    amount_override: Decimal | None = None,
) -> Payment:
    amount = amount_override if amount_override is not None else calculate_service_payment_amount(service)
    amount = _money(Decimal(str(amount)))

    result = await db.execute(
        select(Payment).where(Payment.appointment_id == appointment.id, Payment.store_id == store_id)
    )
    payment = result.scalar_one_or_none()

    if payment:
        if amount > 0:
            payment.amount = amount
        if not payment.preference_id:
            payment.preference_id = f"pref_{appointment.id}"
        if not payment.payment_link:
            payment.payment_link = f"https://payments.shifty.local/pay/{appointment.id}"
        if payment.status not in {
            PaymentStatus.APPROVED.value,
            PaymentStatus.MANUAL_CONFIRMED.value,
            PaymentStatus.REFUNDED.value,
        }:
            payment.status = PaymentStatus.PENDING.value
        return payment

    payment = Payment(
        store_id=store_id,
        appointment_id=appointment.id,
        amount=amount,
        currency="ARS",
        status=PaymentStatus.PENDING.value,
        preference_id=f"pref_{appointment.id}",
        payment_link=f"https://payments.shifty.local/pay/{appointment.id}",
    )
    db.add(payment)
    await db.flush()
    db.add(
        OutboxMessage(
            store_id=store_id,
            event_type="payment.preference.created",
            payload={"appointment_id": appointment.id, "payment_id": payment.id},
        )
    )
    return payment


def sync_appointment_with_payment(appointment: Appointment, payment_status: str) -> None:
    if payment_status in {PaymentStatus.APPROVED.value, PaymentStatus.MANUAL_CONFIRMED.value}:
        if appointment.status in {
            AppointmentStatus.PENDING.value,
            AppointmentStatus.PENDING_PAYMENT.value,
        }:
            appointment.apply_status_transition(AppointmentStatus.CONFIRMED)
        return

    if payment_status == PaymentStatus.REFUNDED.value:
        if appointment.status == AppointmentStatus.PENDING_PAYMENT.value:
            appointment.apply_status_transition(AppointmentStatus.CANCELLED)
        return

    if payment_status in {PaymentStatus.REJECTED.value, PaymentStatus.EXPIRED.value}:
        if appointment.status == AppointmentStatus.PENDING_PAYMENT.value:
            appointment.apply_status_transition(AppointmentStatus.EXPIRED)


def stamp_payment_from_status(payment: Payment, payment_status: str, *, payload: dict | None = None) -> None:
    payment.status = payment_status
    payment.raw_payload = payload or payment.raw_payload
    if payment_status in {PaymentStatus.APPROVED.value, PaymentStatus.MANUAL_CONFIRMED.value}:
        payment.paid_at = payment.paid_at or datetime.now(timezone.utc)
