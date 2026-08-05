from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from json import JSONDecodeError
from urllib.parse import urlencode, urlparse
from typing import cast

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.circuit_breaker import AsyncCircuitBreaker
from core.config import settings
from core.crypto import decrypt_secret, encrypt_secret
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import (
    JsonValue,
    OutboxMessage,
    Payment,
    PaymentGatewayConfig,
    PaymentStatus,
)
from modules.services.model import Service
from modules.stores.model import Store
from modules.users.model import User


ACTIVE_APPOINTMENT_STATUSES = {
    AppointmentStatus.PENDING.value,
    AppointmentStatus.PENDING_PAYMENT.value,
    AppointmentStatus.CONFIRMED.value,
}
MERCADOPAGO_API_BASE_URL = "https://api.mercadopago.com"
_mercadopago_breaker = AsyncCircuitBreaker(
    name="mercadopago",
    failure_threshold=settings.PAYMENTS_CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    recovery_timeout_seconds=settings.PAYMENTS_CIRCUIT_BREAKER_RECOVERY_SECONDS,
)


class MercadoPagoAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        transient: bool = False,
    ) -> None:
        self.status_code = status_code
        self.transient = transient
        super().__init__(message)


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _clean_payload(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: _clean_payload(item) for key, item in value.items() if item is not None
        }
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


async def _resolve_appointment_payer(
    db: AsyncSession, appointment: Appointment
) -> tuple[str | None, str | None]:
    client = appointment.__dict__.get("client")
    if client is None and appointment.client_id:
        result = await db.execute(select(User).where(User.id == appointment.client_id))
        client = result.scalar_one_or_none()

    if client is None:
        return appointment.client_name or None, appointment.client_email

    resolved_name = client.full_name or client.email
    return resolved_name or None, client.email


def _booking_return_url(store: Store, payment: Payment) -> str:
    base_url = settings.FRONTEND_URL.rstrip("/")
    query = urlencode(
        {
            "payment_id": payment.id,
            "store_id": store.public_id,
        }
    )
    return f"{base_url}/booking/{store.slug}?{query}"


def _notification_url(store: Store) -> str:
    base_url = settings.PUBLIC_API_URL.rstrip("/")
    return f"{base_url}/payments/webhooks/mercadopago?store_id={store.public_id}"


def _resolve_checkout_link(payload: dict[str, JsonValue]) -> str | None:
    # Checkout Pro test purchases use test seller/buyer accounts with the
    # regular init_point. Forcing sandbox_init_point in non-production mixes
    # environments and Mercado Pago rejects otherwise valid test payments.
    value = payload.get("init_point") or payload.get("sandbox_init_point")
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        hostname == "mercadopago.com"
        or hostname.endswith(".mercadopago.com")
        or hostname == "mercadopago.com.ar"
        or hostname.endswith(".mercadopago.com.ar")
    ):
        return None
    return value


def calculate_service_payment_amount(
    service: Service, *, base_price: Decimal | None = None
) -> Decimal:
    mode = getattr(service, "deposit_mode", "none") or "none"
    payment_type = getattr(service, "deposit_type", "percent") or "percent"
    raw_amount = getattr(service, "deposit_amount", None)
    service_price = _money(
        base_price if base_price is not None else Decimal(str(service.price or 0))
    )

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
    json_body: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    result = await _mercadopago_breaker.call(
        lambda: _perform_mercadopago_request(
            access_token,
            method=method,
            path=path,
            json_body=json_body,
        ),
        should_record_failure=_should_trip_mercadopago_breaker,
    )
    return cast(dict[str, JsonValue], result)


def _should_trip_mercadopago_breaker(exc: Exception) -> bool:
    return isinstance(exc, MercadoPagoAPIError) and exc.transient


async def _perform_mercadopago_request(
    access_token: str,
    *,
    method: str,
    path: str,
    json_body: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(
            base_url=MERCADOPAGO_API_BASE_URL, timeout=20.0
        ) as client:
            response = await client.request(
                method, path, headers=headers, json=json_body
            )
    except httpx.TimeoutException as exc:
        raise MercadoPagoAPIError(
            "Mercado Pago no respondio a tiempo", transient=True
        ) from exc
    except httpx.RequestError as exc:
        raise MercadoPagoAPIError(
            "Mercado Pago no esta disponible", transient=True
        ) from exc

    if response.status_code >= 500:
        detail = response.text[:400]
        raise MercadoPagoAPIError(
            detail or f"Mercado Pago devolvio HTTP {response.status_code}",
            status_code=response.status_code,
            transient=True,
        )
    if response.status_code >= 400:
        detail = response.text[:400]
        raise MercadoPagoAPIError(
            detail or f"Mercado Pago devolvio HTTP {response.status_code}",
            status_code=response.status_code,
            transient=False,
        )
    if not response.content:
        return {}
    try:
        return cast(dict[str, JsonValue], response.json())
    except (ValueError, JSONDecodeError) as exc:
        raise MercadoPagoAPIError(
            "Mercado Pago devolvio una respuesta invalida", transient=True
        ) from exc


async def _get_gateway_config(
    db: AsyncSession, store_id: str
) -> PaymentGatewayConfig | None:
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
        return None


def _resolve_refresh_token(config: PaymentGatewayConfig | None) -> str | None:
    if not config or not config.encrypted_refresh_token:
        return None
    try:
        return decrypt_secret(config.encrypted_refresh_token)
    except Exception:
        return None


def mercadopago_oauth_is_configured() -> bool:
    return bool(
        settings.MERCADOPAGO_OAUTH_CLIENT_ID
        and settings.MERCADOPAGO_OAUTH_CLIENT_SECRET
        and settings.MERCADOPAGO_OAUTH_REDIRECT_URI
    )


def build_mercadopago_oauth_authorization_url(
    *, state: str, code_challenge: str
) -> str:
    if not mercadopago_oauth_is_configured():
        raise RuntimeError("Mercado Pago OAuth no esta configurado")
    query = urlencode(
        {
            "client_id": settings.MERCADOPAGO_OAUTH_CLIENT_ID,
            "response_type": "code",
            "platform_id": "mp",
            "state": state,
            "redirect_uri": settings.MERCADOPAGO_OAUTH_REDIRECT_URI,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": "read write offline_access",
        }
    )
    return f"{settings.MERCADOPAGO_OAUTH_AUTH_URL}?{query}"


async def _mercadopago_oauth_token_request(
    form_data: dict[str, str],
) -> dict[str, JsonValue]:
    if not mercadopago_oauth_is_configured():
        raise RuntimeError("Mercado Pago OAuth no esta configurado")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{MERCADOPAGO_API_BASE_URL}/oauth/token",
                data=form_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
    except httpx.TimeoutException as exc:
        raise RuntimeError("Mercado Pago no respondio a tiempo durante OAuth") from exc
    except httpx.RequestError as exc:
        raise RuntimeError(
            "Mercado Pago no esta disponible para completar OAuth"
        ) from exc

    if response.status_code >= 400:
        detail = response.text[:400] or f"HTTP {response.status_code}"
        raise RuntimeError(f"Mercado Pago rechazo OAuth: {detail}")

    try:
        return cast(dict[str, JsonValue], response.json())
    except ValueError as exc:
        raise RuntimeError(
            "Mercado Pago devolvio una respuesta OAuth invalida"
        ) from exc


async def exchange_mercadopago_oauth_code(
    *, code: str, code_verifier: str
) -> dict[str, JsonValue]:
    return await _mercadopago_oauth_token_request(
        {
            "client_id": settings.MERCADOPAGO_OAUTH_CLIENT_ID or "",
            "client_secret": settings.MERCADOPAGO_OAUTH_CLIENT_SECRET or "",
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.MERCADOPAGO_OAUTH_REDIRECT_URI or "",
            "code_verifier": code_verifier,
        }
    )


async def refresh_mercadopago_oauth_connection(
    db: AsyncSession,
    *,
    config: PaymentGatewayConfig,
) -> PaymentGatewayConfig:
    refresh_token = _resolve_refresh_token(config)
    if not refresh_token:
        raise RuntimeError("La conexion OAuth de Mercado Pago no tiene refresh token")

    token_payload = await _mercadopago_oauth_token_request(
        {
            "client_id": settings.MERCADOPAGO_OAUTH_CLIENT_ID or "",
            "client_secret": settings.MERCADOPAGO_OAUTH_CLIENT_SECRET or "",
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    )
    apply_mercadopago_oauth_payload(config, token_payload)
    await db.flush()
    return config


def apply_mercadopago_oauth_payload(
    config: PaymentGatewayConfig, token_payload: dict[str, JsonValue]
) -> None:
    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("Mercado Pago no devolvio access_token")

    config.encrypted_access_token = encrypt_secret(access_token) or ""

    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    if refresh_token:
        config.encrypted_refresh_token = encrypt_secret(refresh_token)

    public_key = str(token_payload.get("public_key") or "").strip()
    if public_key:
        config.public_key = public_key

    oauth_user_id = str(token_payload.get("user_id") or "").strip()
    if oauth_user_id:
        config.oauth_user_id = oauth_user_id

    oauth_scope = str(token_payload.get("scope") or "").strip()
    if oauth_scope:
        config.oauth_scope = oauth_scope

    config.connection_mode = "oauth"
    config.oauth_connected_at = datetime.now(timezone.utc)


async def _mercadopago_api_request_for_store(
    db: AsyncSession,
    *,
    store_id: str,
    method: str,
    path: str,
    json_body: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue] | None:
    config = await _get_gateway_config(db, store_id)
    access_token = _resolve_access_token(config)
    if not access_token:
        return None

    try:
        return await _mercadopago_api_request(
            access_token,
            method=method,
            path=path,
            json_body=json_body,
        )
    except MercadoPagoAPIError as exc:
        if (
            exc.status_code == 401
            and config is not None
            and config.connection_mode == "oauth"
            and _resolve_refresh_token(config)
            and mercadopago_oauth_is_configured()
        ):
            refreshed_config = await refresh_mercadopago_oauth_connection(
                db, config=config
            )
            refreshed_access_token = _resolve_access_token(refreshed_config)
            if not refreshed_access_token:
                raise RuntimeError(
                    "No se pudo renovar la conexion OAuth de Mercado Pago"
                )
            return await _mercadopago_api_request(
                refreshed_access_token,
                method=method,
                path=path,
                json_body=json_body,
            )
        raise


async def create_mercadopago_preference(
    db: AsyncSession,
    *,
    payment: Payment,
    appointment: Appointment,
    service: Service,
    store_id: str,
    amount: Decimal,
) -> dict[str, JsonValue] | None:
    config = await _get_gateway_config(db, store_id)
    if not _resolve_access_token(config):
        return None

    store = await _get_store(db, store_id)
    if not store:
        raise RuntimeError("No encontramos la tienda del pago")

    payer_name, payer_email = await _resolve_appointment_payer(db, appointment)

    payload = cast(
        dict[str, JsonValue],
        _clean_payload(
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
                    "name": payer_name,
                    "email": _normalize_payer_email(payer_email),
                },
                "external_reference": appointment.id,
                "notification_url": _notification_url(store),
                "back_urls": {
                    "success": _booking_return_url(store, payment),
                    "failure": _booking_return_url(store, payment),
                    "pending": _booking_return_url(store, payment),
                },
                "auto_return": "approved",
                "binary_mode": True,
                "expires": True,
                # El checkout vence junto con la retencion del slot, para que
                # nadie pague una seña de un turno que ya se libero.
                "expiration_date_to": (
                    appointment.expires_at or appointment.starts_at
                ).isoformat(),
                "metadata": {
                    "appointment_id": appointment.id,
                    "store_id": store.id,
                    "store_public_id": store.public_id,
                    "payment_id": payment.id,
                },
            },
        ),
    )
    return await _mercadopago_api_request_for_store(
        db,
        store_id=store_id,
        method="POST",
        path="/checkout/preferences",
        json_body=payload,
    )


async def expire_mercadopago_preference(
    db: AsyncSession,
    *,
    store_id: str,
    preference_id: str,
) -> None:
    if _is_placeholder_preference(preference_id):
        return
    expiration = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    response = await _mercadopago_api_request_for_store(
        db,
        store_id=store_id,
        method="PUT",
        path=f"/checkout/preferences/{preference_id}",
        json_body={
            "expires": True,
            "expiration_date_to": expiration,
        },
    )
    if response is None:
        raise RuntimeError(
            "No se pudo vencer la preferencia porque la tienda no tiene una conexion activa"
        )


async def fetch_mercadopago_payment(
    db: AsyncSession, *, store_id: str, payment_id: str
) -> dict[str, JsonValue] | None:
    return await _mercadopago_api_request_for_store(
        db,
        store_id=store_id,
        method="GET",
        path=f"/v1/payments/{payment_id}",
    )


async def search_mercadopago_payments(
    db: AsyncSession, *, store_id: str, external_reference: str
) -> list[dict[str, JsonValue]]:
    """Busca en Mercado Pago los pagos asociados a un turno.

    Se usa para conciliar cuando nunca llego el webhook o no pudimos aplicarlo:
    el ``external_reference`` es el id del turno, asi que alcanza para recuperar
    el cobro sin depender de la notificacion.
    """
    query = urlencode(
        {
            "external_reference": external_reference,
            "sort": "date_created",
            "criteria": "desc",
        }
    )
    response = await _mercadopago_api_request_for_store(
        db,
        store_id=store_id,
        method="GET",
        path=f"/v1/payments/search?{query}",
    )
    if not response:
        return []
    results = response.get("results")
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


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
    amount = (
        amount_override
        if amount_override is not None
        else calculate_service_payment_amount(service)
    )
    amount = _money(Decimal(str(amount)))

    original_amount = _money(
        Decimal(str(original_amount if original_amount is not None else amount))
    )
    discount_amount = _money(Decimal(str(discount_amount or 0)))

    result = await db.execute(
        select(Payment).where(
            Payment.appointment_id == appointment.id, Payment.store_id == store_id
        )
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
        should_refresh_provider_link = (
            should_refresh_provider_link
            or _is_placeholder_preference(payment.preference_id)
            or _is_placeholder_payment_link(payment.payment_link)
        )
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
        else:
            raise RuntimeError(
                "La tienda debe conectar su cuenta de Mercado Pago antes de cobrar"
            )

    return payment


def sync_appointment_with_payment(
    appointment: Appointment, payment_status: str
) -> None:
    if payment_status in {
        PaymentStatus.APPROVED.value,
        PaymentStatus.MANUAL_CONFIRMED.value,
    }:
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


def stamp_payment_from_status(
    payment: Payment,
    payment_status: str,
    *,
    payload: dict[str, JsonValue] | None = None,
) -> None:
    if payment.status in {
        PaymentStatus.APPROVED.value,
        PaymentStatus.MANUAL_CONFIRMED.value,
        PaymentStatus.REFUNDED.value,
    } and payment_status in {
        PaymentStatus.PENDING.value,
        PaymentStatus.REJECTED.value,
        PaymentStatus.EXPIRED.value,
    }:
        return
    payment.status = payment_status
    payment.raw_payload = payload or payment.raw_payload
    if payment_status in {
        PaymentStatus.APPROVED.value,
        PaymentStatus.MANUAL_CONFIRMED.value,
    }:
        payment.paid_at = payment.paid_at or datetime.now(timezone.utc)
