from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Environment, settings
from core.crypto import decrypt_secret
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import OutboxMessage, Payment, PaymentGatewayConfig, PaymentStatus
from modules.services.model import Service
from modules.stores.model import Store


ACTIVE_APPOINTMENT_STATUSES = {
    AppointmentStatus.PENDING.value,
    AppointmentStatus.PENDING_PAYMENT.value,
    AppointmentStatus.CONFIRMED.value,
}
MERCADOPAGO_API_BASE_URL = "https://api.mercadopago.com"


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _clean_payload(value):
    if isinstance(value, dict):
        return {key: _clean_payload(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_clean_payload(item) for item in value if item is not None]
    return value


def _is_placeholder_preference(preference_id: str | None) -> bool:
    return not preference_id or preference_id.startswith("pref_")


def _is_placeholder_payment_link(payment_link: str | None) -> bool:
    return not payment_link or payment_link.startswith("https://payments.shifty.local/")


def _normalize_payer_email(email: str | None) -> str | None:
    if not email:
        return None
    if email.endswith(".noreply"):
        return None
    return email


def _booking_return_url(store: Store, appointment: Appointment, payment_status: str) -> str:
    base_url = settings.FRONTEND_URL.rstrip("/")
    query = urlencode(
        {
            "payment_status": payment_status,
            "appointment_id": appointment.public_id,
            "store_id": store.public_id,
        }
    )
    return f"{base_url}/booking/{store.slug}?{query}"


def _notification_url(store: Store) -> str:
    base_url = settings.PUBLIC_API_URL.rstrip("/")
    return f"{base_url}/payments/webhooks/mercadopago?store_id={store.public_id}"


def _resolve_checkout_link(payload: dict) -> str | None:
    if settings.ENV == Environment.PRODUCTION:
        return payload.get("init_point") or payload.get("sandbox_init_point")
    return payload.get("sandbox_init_point") or payload.get("init_point")


def calculate_service_payment_amount(service: Service, *, base_price: Decimal | None = None) -> Decimal:
    mode = getattr(service, "deposit_mode", "none") or "none"
    payment_type = getattr(service, "deposit_type", "percent") or "percent"
    raw_amount = getattr(service, "deposit_amount", None)
    service_price = _money(base_price if base_price is not None else Decimal(str(service.price or 0)))

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


async def _mercadopago_api_request(
    access_token: str,
    *,
    method: str,
    path: str,
    json_body: dict | None = None,
) -> dict:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(base_url=MERCADOPAGO_API_BASE_URL, timeout=20.0) as client:
        response = await client.request(method, path, headers=headers, json=json_body)
    if response.status_code >= 400:
        detail = response.text[:400]
        raise RuntimeError(detail or f"Mercado Pago devolvio HTTP {response.status_code}")
    if not response.content:
        return {}
    return response.json()


async def _get_gateway_config(db: AsyncSession, store_id: str) -> PaymentGatewayConfig | None:
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.store_id == store_id,
            PaymentGatewayConfig.provider == "mercadopago",
        )
    )
    return result.scalar_one_or_none()


async def _get_store(db: AsyncSession, store_id: str) -> Store | None:
    result = await db.execute(select(Store).where(Store.id == store_id))
    return result.scalar_one_or_none()


def _resolve_access_token(config: PaymentGatewayConfig | None) -> str | None:
    if not config or not config.encrypted_access_token:
        return None
    try:
        return decrypt_secret(config.encrypted_access_token)
    except Exception:
        return config.encrypted_access_token


async def create_mercadopago_preference(
    db: AsyncSession,
    *,
    payment: Payment,
    appointment: Appointment,
    service: Service,
    store_id: str,
    amount: Decimal,
) -> dict | None:
    config = await _get_gateway_config(db, store_id)
    access_token = _resolve_access_token(config)
    if not access_token:
        return None

    store = await _get_store(db, store_id)
    if not store:
        raise RuntimeError("No encontramos la tienda del pago")

    payload = _clean_payload(
        {
            "items": [
                {
                    "id": service.public_id,
                    "title": service.name,
                    "description": service.description,
                    "picture_url": service.image_url,
                    "quantity": 1,
                    "currency_id": payment.currency or "ARS",
                    "unit_price": float(amount),
                }
            ],
            "payer": {
                "name": appointment.client_name,
                "email": _normalize_payer_email(appointment.client_email),
            },
            "external_reference": appointment.id,
            "notification_url": _notification_url(store),
            "back_urls": {
                "success": _booking_return_url(store, appointment, "approved"),
                "failure": _booking_return_url(store, appointment, "rejected"),
                "pending": _booking_return_url(store, appointment, "pending"),
            },
            "auto_return": "approved",
            "metadata": {
                "appointment_id": appointment.id,
                "store_id": store.id,
                "store_public_id": store.public_id,
                "payment_id": payment.id,
            },
        }
    )
    return await _mercadopago_api_request(access_token, method="POST", path="/checkout/preferences", json_body=payload)


async def fetch_mercadopago_payment(db: AsyncSession, *, store_id: str, payment_id: str) -> dict | None:
    config = await _get_gateway_config(db, store_id)
    access_token = _resolve_access_token(config)
    if not access_token:
        return None
    return await _mercadopago_api_request(
        access_token,
        method="GET",
        path=f"/v1/payments/{payment_id}",
    )


async def ensure_payment_preference(
    db: AsyncSession,
    *,
    appointment: Appointment,
    service: Service,
    store_id: str,
    amount_override: Decimal | None = None,
    original_amount: Decimal | None = None,
    discount_amount: Decimal | None = None,
    promotion_code: str | None = None,
    create_provider_link: bool = True,
) -> Payment:
    amount = amount_override if amount_override is not None else calculate_service_payment_amount(service)
    amount = _money(Decimal(str(amount)))

    original_amount = _money(Decimal(str(original_amount if original_amount is not None else amount)))
    discount_amount = _money(Decimal(str(discount_amount or 0)))

    result = await db.execute(
        select(Payment).where(Payment.appointment_id == appointment.id, Payment.store_id == store_id)
    )
    payment = result.scalar_one_or_none()
    should_refresh_provider_link = False

    if payment:
        if amount > 0:
            should_refresh_provider_link = payment.amount != amount
            payment.amount = amount
        payment.original_amount = original_amount
        payment.discount_amount = discount_amount
        payment.promotion_code = promotion_code
        if payment.status not in {
            PaymentStatus.APPROVED.value,
            PaymentStatus.MANUAL_CONFIRMED.value,
            PaymentStatus.REFUNDED.value,
        }:
            payment.status = PaymentStatus.PENDING.value
        should_refresh_provider_link = should_refresh_provider_link or _is_placeholder_preference(payment.preference_id) or _is_placeholder_payment_link(payment.payment_link)
    else:
        payment = Payment(
            store_id=store_id,
            appointment_id=appointment.id,
            amount=amount,
            original_amount=original_amount,
            discount_amount=discount_amount,
            currency="ARS",
            status=PaymentStatus.PENDING.value,
            preference_id=f"pref_{appointment.id}",
            payment_link=f"https://payments.shifty.local/pay/{appointment.id}",
            promotion_code=promotion_code,
        )
        db.add(payment)
        await db.flush()
        should_refresh_provider_link = True
        db.add(
            OutboxMessage(
                store_id=store_id,
                event_type="payment.preference.created",
                payload={"appointment_id": appointment.id, "payment_id": payment.id},
            )
        )

    if create_provider_link and should_refresh_provider_link:
        preference_payload = await create_mercadopago_preference(
            db,
            payment=payment,
            appointment=appointment,
            service=service,
            store_id=store_id,
            amount=amount,
        )
        if preference_payload:
            preference_id = str(preference_payload.get("id") or "").strip()
            payment_link = _resolve_checkout_link(preference_payload)
            if not preference_id or not payment_link:
                raise RuntimeError("Mercado Pago no devolvio una preferencia valida")
            payment.preference_id = preference_id
            payment.payment_link = payment_link
            payment.raw_payload = preference_payload

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
