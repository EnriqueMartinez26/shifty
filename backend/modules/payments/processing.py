from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import NotificationType
from modules.payments.model import (
    OutboxMessage,
    Payment,
    PaymentGatewayConfig,
    PaymentStatus,
)
from modules.payments.model import JsonValue
from modules.services.model import Service
from modules.payments.service import (
    fetch_mercadopago_payment,
    stamp_payment_from_status,
    sync_appointment_with_payment,
)


def resolve_payment_status(payload: dict[str, Any]) -> str | None:
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
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
    return mapping.get(normalized) or (
        normalized if normalized in allowed_statuses else None
    )


async def enrich_mercadopago_webhook_payload(
    db: AsyncSession,
    *,
    store_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    payment_id = str(data.get("id") or payload.get("payment_id") or "").strip()
    if not payment_id:
        return payload

    try:
        payment_details = await fetch_mercadopago_payment(
            db, store_id=store_id, payment_id=payment_id
        )
    except Exception:
        return payload

    if not payment_details:
        return payload

    merged_data = dict(data)
    merged_data.update(
        {
            "id": payment_details.get("id", merged_data.get("id")),
            "status": payment_details.get("status", merged_data.get("status")),
            "external_reference": payment_details.get(
                "external_reference", merged_data.get("external_reference")
            ),
            "metadata": payment_details.get("metadata") or merged_data.get("metadata"),
            "date_approved": payment_details.get(
                "date_approved", merged_data.get("date_approved")
            ),
            "transaction_amount": payment_details.get("transaction_amount"),
            "currency_id": payment_details.get("currency_id"),
            "collector_id": payment_details.get("collector_id"),
            "live_mode": payment_details.get("live_mode"),
            "preference_id": payment_details.get(
                "preference_id", merged_data.get("preference_id")
            ),
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


async def find_payment_for_webhook(
    db: AsyncSession, store_id: str, payload: dict[str, Any]
) -> Payment | None:
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    raw_metadata = data.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}

    appointment_id = (
        metadata.get("appointment_id")
        or payload.get("appointment_id")
        or payload.get("external_reference")
        or data.get("external_reference")
    )
    preference_id = data.get("preference_id") or payload.get("preference_id")
    external_payment_id = (
        str(data.get("id") or payload.get("payment_id") or "").strip() or None
    )

    if external_payment_id:
        result = await db.execute(
            select(Payment)
            .where(
                Payment.store_id == store_id,
                Payment.external_payment_id == external_payment_id,
            )
            .with_for_update()
        )
        payment = result.scalar_one_or_none()
        if payment:
            return payment

    if preference_id:
        result = await db.execute(
            select(Payment)
            .where(
                Payment.store_id == store_id,
                Payment.preference_id == str(preference_id),
            )
            .with_for_update()
        )
        payment = result.scalar_one_or_none()
        if payment:
            return payment

    if appointment_id:
        result = await db.execute(
            select(Payment)
            .where(
                Payment.store_id == store_id,
                Payment.appointment_id == str(appointment_id),
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    return None


async def _validate_payment_integrity(
    db: AsyncSession,
    *,
    store_id: str,
    payment: Payment,
    payload: dict[str, Any],
) -> None:
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    raw_metadata = data.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}

    expected_values = {
        "payment_id": payment.id,
        "appointment_id": payment.appointment_id,
        "store_id": store_id,
    }
    for key, expected in expected_values.items():
        received = str(metadata.get(key) or "").strip()
        if received and received != str(expected):
            raise RuntimeError(f"Mercado Pago devolvio metadata inconsistente: {key}")

    external_reference = str(
        data.get("external_reference") or payload.get("external_reference") or ""
    ).strip()
    if external_reference and external_reference != payment.appointment_id:
        raise RuntimeError("Mercado Pago devolvio una referencia externa inconsistente")

    received_amount = data.get("transaction_amount")
    if received_amount is not None and Decimal(str(received_amount)).quantize(
        Decimal("0.01")
    ) != Decimal(str(payment.amount)).quantize(Decimal("0.01")):
        raise RuntimeError("El importe acreditado no coincide con la seña esperada")

    currency = str(data.get("currency_id") or "").strip()
    if currency and currency != payment.currency:
        raise RuntimeError("La moneda acreditada no coincide con la esperada")

    preference_id = str(data.get("preference_id") or "").strip()
    if (
        preference_id
        and payment.preference_id
        and preference_id != payment.preference_id
    ):
        raise RuntimeError("La preferencia acreditada no coincide con la esperada")

    config_result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.store_id == store_id,
            PaymentGatewayConfig.provider == "mercadopago",
        )
    )
    config = config_result.scalar_one_or_none()
    collector_id = str(data.get("collector_id") or "").strip()
    if config and config.oauth_user_id and collector_id:
        if collector_id != config.oauth_user_id:
            raise RuntimeError("El cobro pertenece a otra cuenta de Mercado Pago")


async def _notify_payment_approved(
    db: AsyncSession, *, store_id: str, payment: Payment
) -> None:
    """Deja en el outbox el aviso de seña acreditada para el panel de la tienda."""
    result = await db.execute(
        select(Appointment, Service)
        .join(Service, Appointment.service_id == Service.id)
        .where(Appointment.id == payment.appointment_id)
    )
    row = result.first()
    appointment, service = row if row else (None, None)

    db.add(
        OutboxMessage(
            store_id=store_id,
            event_type=NotificationType.PAYMENT_APPROVED.value,
            payload={
                "appointment_id": payment.appointment_id,
                "payment_id": payment.id,
                "amount": str(payment.amount),
                "client_name": appointment.client_name if appointment else None,
                "service_name": service.name if service else None,
            },
        )
    )


async def apply_mercadopago_webhook_payload(
    db: AsyncSession, *, store_id: str, payload: dict[str, Any]
) -> bool:
    payment = await find_payment_for_webhook(db, store_id, payload)
    payment_status = resolve_payment_status(payload)
    if not payment or not payment_status:
        return False

    await _validate_payment_integrity(
        db, store_id=store_id, payment=payment, payload=payload
    )

    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    external_payment_id = str(data.get("id") or payload.get("payment_id") or "").strip()
    if external_payment_id:
        payment.external_payment_id = external_payment_id

    was_settled = payment.status in {
        PaymentStatus.APPROVED.value,
        PaymentStatus.MANUAL_CONFIRMED.value,
    }
    stamp_payment_from_status(
        payment,
        payment_status,
        payload=cast(dict[str, JsonValue], payload),
    )
    if not was_settled and payment.status == PaymentStatus.APPROVED.value:
        await _notify_payment_approved(db, store_id=store_id, payment=payment)
    appointment_result = await db.execute(
        select(Appointment)
        .where(
            Appointment.id == payment.appointment_id, Appointment.store_id == store_id
        )
        .with_for_update()
    )
    appointment = appointment_result.scalar_one_or_none()
    if appointment:
        appointment_start = appointment.starts_at
        if appointment_start.tzinfo is None:
            appointment_start = appointment_start.replace(tzinfo=timezone.utc)
        if (
            payment_status == PaymentStatus.APPROVED.value
            and appointment.status == AppointmentStatus.PENDING_PAYMENT.value
            and appointment_start <= datetime.now(timezone.utc)
        ):
            appointment.apply_status_transition(AppointmentStatus.EXPIRED)
        sync_appointment_with_payment(appointment, payment.status)
    return True
