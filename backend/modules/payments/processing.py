from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.payments.model import Payment, PaymentStatus
from modules.payments.service import (
    fetch_mercadopago_payment,
    stamp_payment_from_status,
    sync_appointment_with_payment,
)


def resolve_payment_status(payload: dict[str, Any]) -> str | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    candidate = (
        data.get("status")
        or payload.get("status")
        or payload.get("action")
        or payload.get("topic")
    )
    if not candidate:
        return None

    normalized = str(candidate).lower()
    if normalized == "payment.updated" and data.get("status"):
        normalized = str(data.get("status")).lower()

    mapping = {
        "approved": PaymentStatus.APPROVED.value,
        "accredited": PaymentStatus.APPROVED.value,
        "pending": PaymentStatus.PENDING.value,
        "in_process": PaymentStatus.PENDING.value,
        "rejected": PaymentStatus.REJECTED.value,
        "cancelled": PaymentStatus.REJECTED.value,
        "refunded": PaymentStatus.REFUNDED.value,
        "expired": PaymentStatus.EXPIRED.value,
    }
    allowed_statuses = {status.value for status in PaymentStatus}
    return mapping.get(normalized) or (normalized if normalized in allowed_statuses else None)


async def enrich_mercadopago_webhook_payload(
    db: AsyncSession,
    *,
    store_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    payment_id = str(data.get("id") or payload.get("payment_id") or "").strip()
    if not payment_id:
        return payload

    try:
        payment_details = await fetch_mercadopago_payment(db, store_id=store_id, payment_id=payment_id)
    except Exception:
        return payload

    if not payment_details:
        return payload

    merged_data = dict(data)
    merged_data.update(
        {
            "id": payment_details.get("id", merged_data.get("id")),
            "status": payment_details.get("status", merged_data.get("status")),
            "external_reference": payment_details.get("external_reference", merged_data.get("external_reference")),
            "preference_id": merged_data.get("preference_id"),
            "metadata": payment_details.get("metadata") or merged_data.get("metadata"),
            "date_approved": payment_details.get("date_approved", merged_data.get("date_approved")),
        }
    )
    merged_payload = dict(payload)
    merged_payload["data"] = merged_data
    merged_payload["status"] = payment_details.get("status", payload.get("status"))
    merged_payload["external_reference"] = payment_details.get(
        "external_reference",
        payload.get("external_reference"),
    )
    return merged_payload


async def find_payment_for_webhook(db: AsyncSession, store_id: str, payload: dict[str, Any]) -> Payment | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}

    appointment_id = (
        metadata.get("appointment_id")
        or payload.get("appointment_id")
        or payload.get("external_reference")
        or data.get("external_reference")
    )
    preference_id = data.get("preference_id") or payload.get("preference_id")
    external_payment_id = str(data.get("id") or payload.get("payment_id") or "").strip() or None

    if external_payment_id:
        result = await db.execute(
            select(Payment).where(Payment.store_id == store_id, Payment.external_payment_id == external_payment_id)
        )
        payment = result.scalar_one_or_none()
        if payment:
            return payment

    if preference_id:
        result = await db.execute(
            select(Payment).where(Payment.store_id == store_id, Payment.preference_id == str(preference_id))
        )
        payment = result.scalar_one_or_none()
        if payment:
            return payment

    if appointment_id:
        result = await db.execute(
            select(Payment).where(Payment.store_id == store_id, Payment.appointment_id == str(appointment_id))
        )
        return result.scalar_one_or_none()

    return None


async def apply_mercadopago_webhook_payload(db: AsyncSession, *, store_id: str, payload: dict[str, Any]) -> bool:
    payment = await find_payment_for_webhook(db, store_id, payload)
    payment_status = resolve_payment_status(payload)
    if not payment or not payment_status:
        return False

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    external_payment_id = str(data.get("id") or payload.get("payment_id") or "").strip()
    if external_payment_id:
        payment.external_payment_id = external_payment_id

    stamp_payment_from_status(payment, payment_status, payload=payload)
    appointment_result = await db.execute(
        select(Appointment).where(Appointment.id == payment.appointment_id, Appointment.store_id == store_id)
    )
    appointment = appointment_result.scalar_one_or_none()
    if appointment:
        sync_appointment_with_payment(appointment, payment.status)
    return True
