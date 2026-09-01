from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
from typing import Annotated, Any

from core.router import CanonicalAPIRouter
from fastapi import Depends, Path, Query, Request, status
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.circuit_breaker import CircuitBreakerOpenError
from core.config import Environment, settings
from core.crypto import encrypt_secret
from core.database import _apply_tenant_context, get_db, set_tenant_context
from core.redis import get_redis
from core.exceptions import (
    AppException,
    AppointmentNotFoundException,
    FeatureDisabledException,
    PermissionDeniedException,
    ResourceNotFoundException,
    StoreNotFoundException,
    ValidationException,
    WebhookException,
)
from core.feature_flags import is_store_feature_enabled
from core.validation import PUBLIC_ID_PATTERN
from modules.appointments.model import Appointment
from modules.auth.dependencies import get_current_user
from modules.payments.jobs import process_outbox_batch
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
from modules.payments.oauth_state import (
    InvalidOAuthStateError,
    create_mercadopago_oauth_state,
    mercadopago_oauth_state_cache_key,
    parse_mercadopago_oauth_state,
)
from modules.payments.service import (
    apply_mercadopago_oauth_payload,
    build_mercadopago_oauth_authorization_url,
    calculate_service_payment_amount,
    exchange_mercadopago_oauth_code,
    ensure_payment_preference,
    mercadopago_oauth_is_configured,
    refresh_mercadopago_oauth_connection,
    stamp_payment_from_status,
    sync_appointment_with_payment,
)
from modules.payments.schemas import (
    GatewayConfigResponse,
    OAuthDisconnectResponse,
    GatewayConfigUpsert,
    ManualPaymentRequest,
    MercadoPagoOAuthStartResponse,
    OutboxProcessResponse,
    OutboxStatsResponse,
    PaymentPreferenceResponse,
    PaymentResponse,
    ReconciliationSummaryResponse,
    RefundRequest,
)
from modules.services.model import Service
from modules.stores.model import Store
from modules.users.model import User, UserRole

router = CanonicalAPIRouter(prefix="/payments", tags=["Payments"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


def _gateway_config_response(
    config: PaymentGatewayConfig | None,
) -> GatewayConfigResponse:
    if not config:
        return GatewayConfigResponse(provider="mercadopago", configured=False)
    return GatewayConfigResponse(
        provider=config.provider,
        configured=True,
        public_key=config.public_key,
        access_token_masked="********",
    )


def _payment_preference_response(payment: Payment) -> PaymentPreferenceResponse:
    return PaymentPreferenceResponse(
        payment_public_id=payment.id,
        appointment_id=payment.appointment_id,
        amount=payment.amount,
        currency=payment.currency,
        preference_id=payment.preference_id,
        payment_link=payment.payment_link,
        status=payment.status,
    )


def _payment_response(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        public_id=payment.id,
        appointment_id=payment.appointment_id,
        amount=payment.amount,
        currency=payment.currency,
        status=payment.status,
        paid_at=payment.paid_at,
    )


def _payment_amount_for_service(
    service: Service, requested_amount: Decimal | None = None
) -> Decimal:
    if requested_amount is not None:
        return requested_amount
    return calculate_service_payment_amount(service) or Decimal(str(service.price))


def _require_payment_manager(user: User) -> None:
    if user.role not in (UserRole.ADMIN, UserRole.STAFF) and not user.is_global_admin:
        raise PermissionDeniedException(action="No tenes permiso para gestionar pagos")


def _require_payment_admin(user: User) -> None:
    if user.role != UserRole.ADMIN and not user.is_global_admin:
        raise PermissionDeniedException(
            action="Solo administradores pueden ejecutar esta accion"
        )


async def _ensure_payments_feature_enabled(db: AsyncSession, user: User) -> None:
    result = await db.execute(select(Store).where(Store.id == user.store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise StoreNotFoundException()
    if not is_store_feature_enabled(store.feature_flags, "payments"):
        raise FeatureDisabledException(feature="payments")


async def _get_payment_by_id(
    db: AsyncSession, payment_id: str, store_id: str
) -> Payment:
    result = await db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.store_id == store_id)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise ResourceNotFoundException(resource="Pago", identifier=payment_id)
    return payment


def _parse_signature_header(signature_header: str) -> tuple[str, str] | None:
    parts: dict[str, str] = {}
    for chunk in signature_header.split(","):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        parts[key.strip()] = value.strip()
    ts = parts.get("ts")
    v1 = parts.get("v1")
    if not ts or not v1:
        return None
    return ts, v1


def _resolve_webhook_data_id(payload: dict[str, Any], query_data_id: str | None) -> str:
    raw_data = payload.get("data")
    payload_data_id = raw_data.get("id") if isinstance(raw_data, dict) else None
    candidate = payload_data_id or query_data_id or payload.get("id")
    return str(candidate or "").strip()


def _webhook_event_id(payload: dict[str, Any]) -> str:
    event_id = str(
        payload.get("id")
        or payload.get("data", {}).get("id")
        or payload.get("resource")
        or ""
    ).strip()
    if not event_id:
        raise WebhookException(message="Webhook sin identificador")
    return f"mercadopago:{event_id}"


async def _resolve_store_for_webhook(
    db: AsyncSession, store_reference: str | None
) -> tuple[str, PaymentGatewayConfig]:
    if not store_reference:
        raise WebhookException(message="store_id invalido para webhook")

    config_result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.store_id == store_reference,
            PaymentGatewayConfig.provider == "mercadopago",
        )
    )
    config = config_result.scalar_one_or_none()
    if config:
        return store_reference, config

    store_result = await db.execute(
        select(Store).where(Store.public_id == store_reference)
    )
    store = store_result.scalar_one_or_none()
    if not store:
        raise WebhookException(message="store_id invalido para webhook")

    config_result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.store_id == store.id,
            PaymentGatewayConfig.provider == "mercadopago",
        )
    )
    config = config_result.scalar_one_or_none()
    if not config:
        raise WebhookException(message="Webhook secret no configurado")
    return store.id, config


async def _validate_mercadopago_signature(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    request: Request,
    store_reference: str | None,
) -> str:
    resolved_store_id, _config = await _resolve_store_for_webhook(db, store_reference)
    secret = settings.MERCADOPAGO_WEBHOOK_SECRET
    if not secret and settings.ENV != "production":
        secret = _config.webhook_secret
    if not secret:
        raise WebhookException(message="Webhook secret no configurado")

    signature_header = request.headers.get("x-signature", "")
    request_id = request.headers.get("x-request-id", "")
    if not signature_header or not request_id:
        raise WebhookException(message="Headers de firma faltantes")

    parsed = _parse_signature_header(signature_header)
    if not parsed:
        raise WebhookException(message="Header x-signature invalido")

    ts, received_v1 = parsed
    try:
        webhook_timestamp = int(ts)
    except ValueError as exc:
        raise WebhookException(message="Timestamp de webhook invalido") from exc
    now_timestamp = int(datetime.now(timezone.utc).timestamp())
    if (
        abs(now_timestamp - webhook_timestamp)
        > settings.MERCADOPAGO_WEBHOOK_MAX_AGE_SECONDS
    ):
        raise WebhookException(
            message="Webhook vencido",
            http_status=status.HTTP_401_UNAUTHORIZED,
            error_code="STALE_WEBHOOK",
        )
    data_id = _resolve_webhook_data_id(payload, request.query_params.get("data.id"))
    if not data_id:
        raise WebhookException(message="No se pudo resolver data.id del webhook")

    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    expected_v1 = hmac.new(
        secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(received_v1.lower(), expected_v1.lower()):
        raise WebhookException(
            message="Firma de webhook invalida",
            http_status=status.HTTP_401_UNAUTHORIZED,
            error_code="INVALID_SIGNATURE",
        )

    return resolved_store_id


async def _get_appointment_with_service(
    db: AsyncSession, appointment_id: str, store_id: str
) -> tuple[Appointment, Service]:
    from sqlalchemy.orm import joinedload

    result = await db.execute(
        select(Appointment, Service)
        .options(joinedload(Appointment.client))
        .join(Service, Appointment.service_id == Service.id)
        .where(Appointment.id == appointment_id, Appointment.store_id == store_id)
    )
    row = result.first()
    if not row:
        raise AppointmentNotFoundException(public_id=appointment_id)
    return row[0], row[1]


async def _count_store_rows(
    db: AsyncSession,
    selectable: type[Payment] | type[WebhookInbox] | type[OutboxMessage],
    *conditions: Any,
) -> int:
    total = await db.scalar(
        select(func.count()).select_from(selectable).where(*conditions)
    )
    return int(total or 0)


def _payment_status_count_query(store_id: str, status_value: str) -> Any:
    return (
        select(func.count())
        .select_from(Payment)
        .where(Payment.store_id == store_id, Payment.status == status_value)
    )


def _payment_status_sum_query(store_id: str, status_value: str) -> Any:
    return select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.store_id == store_id,
        Payment.status == status_value,
    )


def _mercadopago_oauth_required() -> None:
    if not mercadopago_oauth_is_configured():
        raise AppException(
            message="Mercado Pago OAuth no esta configurado en el backend",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="MERCADOPAGO_OAUTH_NOT_CONFIGURED",
        )


def _oauth_frontend_redirect(result: str) -> RedirectResponse:
    target = (
        f"{settings.FRONTEND_URL.rstrip('/')}/dashboard/settings"
        f"?tab=payments&mercadopago={result}"
    )
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/gateway-config", response_model=GatewayConfigResponse)
async def get_gateway_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GatewayConfigResponse:
    _require_payment_manager(user)
    await _ensure_payments_feature_enabled(db, user)
    result = await db.execute(
        select(PaymentGatewayConfig)
        .where(PaymentGatewayConfig.store_id == user.store_id)
        .limit(1)
    )
    config = result.scalar_one_or_none()
    if not config:
        return GatewayConfigResponse(
            provider="mercadopago",
            configured=False,
            oauth_supported=mercadopago_oauth_is_configured(),
        )
    return GatewayConfigResponse(
        provider=config.provider,
        configured=True,
        public_key=config.public_key,
        access_token_masked="********",
        connection_mode=config.connection_mode,
        oauth_user_id=config.oauth_user_id,
        oauth_connected_at=config.oauth_connected_at,
        oauth_supported=mercadopago_oauth_is_configured(),
    )


@router.put("/gateway-config", response_model=GatewayConfigResponse)
async def upsert_gateway_config(
    data: GatewayConfigUpsert,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GatewayConfigResponse:
    _require_payment_admin(user)
    await _ensure_payments_feature_enabled(db, user)
    if settings.ENV == Environment.PRODUCTION:
        raise ValidationException(
            "En produccion, la cuenta de Mercado Pago se configura exclusivamente mediante OAuth"
        )
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.store_id == user.store_id,
            PaymentGatewayConfig.provider == data.provider,
        )
    )
    config = result.scalar_one_or_none()
    encrypted_access_token = (
        encrypt_secret(data.access_token) if data.access_token else None
    )
    provided_fields = data.model_fields_set
    if not config and not encrypted_access_token:
        raise ValidationException(
            "Debes ingresar un access token para configurar el gateway"
        )
    if not config:
        config = PaymentGatewayConfig(
            store_id=user.store_id,
            provider=data.provider,
            encrypted_access_token=encrypted_access_token or "",
            public_key=data.public_key,
            webhook_secret=data.webhook_secret,
            connection_mode="manual",
        )
        db.add(config)
    else:
        if encrypted_access_token:
            config.encrypted_access_token = encrypted_access_token
            config.connection_mode = "manual"
            config.encrypted_refresh_token = None
            config.oauth_user_id = None
            config.oauth_scope = None
            config.oauth_connected_at = None
        if "public_key" in provided_fields:
            config.public_key = data.public_key
        if "webhook_secret" in provided_fields:
            config.webhook_secret = data.webhook_secret
    await db.commit()
    await db.refresh(config)
    return GatewayConfigResponse(
        provider=config.provider,
        configured=True,
        public_key=config.public_key,
        access_token_masked="********",
        connection_mode=config.connection_mode,
        oauth_user_id=config.oauth_user_id,
        oauth_connected_at=config.oauth_connected_at,
        oauth_supported=mercadopago_oauth_is_configured(),
    )


@router.post("/mercadopago/oauth/start", response_model=MercadoPagoOAuthStartResponse)
async def start_mercadopago_oauth(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> MercadoPagoOAuthStartResponse:
    _require_payment_admin(user)
    await _ensure_payments_feature_enabled(db, user)
    _mercadopago_oauth_required()

    state, expires_at, code_verifier, code_challenge = create_mercadopago_oauth_state(
        store_id=user.store_id,
        actor_id=user.id,
        ttl_seconds=settings.MERCADOPAGO_OAUTH_STATE_TTL_SECONDS,
    )
    stored = await redis.set(
        mercadopago_oauth_state_cache_key(state),
        code_verifier,
        ex=settings.MERCADOPAGO_OAUTH_STATE_TTL_SECONDS,
        nx=True,
    )
    if not stored:
        raise AppException(
            message="No se pudo iniciar la conexion segura con Mercado Pago",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="OAUTH_STATE_STORAGE_FAILED",
        )
    auth_url = build_mercadopago_oauth_authorization_url(
        state=state, code_challenge=code_challenge
    )
    return MercadoPagoOAuthStartResponse(
        auth_url=auth_url,
        qr_url=auth_url,
        expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
    )


@router.get("/mercadopago/oauth/callback", response_class=RedirectResponse)
async def mercadopago_oauth_callback(
    code: Annotated[str | None, Query(min_length=3, max_length=500)] = None,
    state: Annotated[str | None, Query(min_length=10, max_length=4000)] = None,
    error: Annotated[str | None, Query(max_length=120)] = None,
    error_description: Annotated[str | None, Query(max_length=500)] = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> RedirectResponse:
    _mercadopago_oauth_required()
    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)
        if error:
            return _oauth_frontend_redirect("denied")
        if not code or not state:
            return _oauth_frontend_redirect("invalid")

        try:
            state_payload = parse_mercadopago_oauth_state(state)
        except InvalidOAuthStateError:
            return _oauth_frontend_redirect("invalid")

        cached_verifier = await redis.getdel(mercadopago_oauth_state_cache_key(state))
        if not cached_verifier:
            return _oauth_frontend_redirect("expired")
        code_verifier = (
            cached_verifier.decode("utf-8")
            if isinstance(cached_verifier, bytes)
            else str(cached_verifier)
        )

        actor_result = await db.execute(
            select(User).where(
                User.id == str(state_payload["actor_id"]),
                User.store_id == str(state_payload["store_id"]),
                User.role == UserRole.ADMIN,
                User.is_active.is_(True),
            )
        )
        if actor_result.scalar_one_or_none() is None:
            return _oauth_frontend_redirect("forbidden")

        try:
            token_payload = await exchange_mercadopago_oauth_code(
                code=code, code_verifier=code_verifier
            )
        except RuntimeError:
            return _oauth_frontend_redirect("exchange_failed")

        result = await db.execute(
            select(PaymentGatewayConfig).where(
                PaymentGatewayConfig.store_id == state_payload["store_id"],
                PaymentGatewayConfig.provider == "mercadopago",
            )
        )
        config = result.scalar_one_or_none()
        if not config:
            config = PaymentGatewayConfig(
                store_id=str(state_payload["store_id"]),
                provider="mercadopago",
                encrypted_access_token="pending",
                connection_mode="oauth",
            )
            db.add(config)

        apply_mercadopago_oauth_payload(config, token_payload)
        await db.commit()

        return _oauth_frontend_redirect("connected")
    finally:
        set_tenant_context(None, False)


@router.post("/mercadopago/oauth/refresh", response_model=GatewayConfigResponse)
async def refresh_mercadopago_oauth(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GatewayConfigResponse:
    _require_payment_admin(user)
    await _ensure_payments_feature_enabled(db, user)
    _mercadopago_oauth_required()

    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.store_id == user.store_id,
            PaymentGatewayConfig.provider == "mercadopago",
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise ResourceNotFoundException(
            resource="Conexion de Mercado Pago", identifier=user.store_id
        )

    try:
        config = await refresh_mercadopago_oauth_connection(db, config=config)
    except RuntimeError as exc:
        raise AppException(
            message=str(exc),
            http_status=status.HTTP_409_CONFLICT,
            error_code="MERCADOPAGO_REFRESH_FAILED",
        )
    await db.commit()
    await db.refresh(config)
    return GatewayConfigResponse(
        provider=config.provider,
        configured=True,
        public_key=config.public_key,
        access_token_masked="********",
        connection_mode=config.connection_mode,
        oauth_user_id=config.oauth_user_id,
        oauth_connected_at=config.oauth_connected_at,
        oauth_supported=mercadopago_oauth_is_configured(),
    )


@router.delete("/mercadopago/oauth/connection", response_model=OAuthDisconnectResponse)
async def disconnect_mercadopago_oauth(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OAuthDisconnectResponse:
    _require_payment_admin(user)
    await _ensure_payments_feature_enabled(db, user)

    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.store_id == user.store_id,
            PaymentGatewayConfig.provider == "mercadopago",
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        return OAuthDisconnectResponse(disconnected=False)

    await db.delete(config)
    await db.commit()
    return OAuthDisconnectResponse(disconnected=True)


@router.post("/preferences/{appointment_id}", response_model=PaymentPreferenceResponse)
async def create_payment_preference(
    appointment_id: PublicIdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentPreferenceResponse:
    _require_payment_manager(user)
    await _ensure_payments_feature_enabled(db, user)
    appointment, service = await _get_appointment_with_service(
        db, appointment_id, user.store_id
    )
    try:
        payment = await ensure_payment_preference(
            db,
            appointment=appointment,
            service=service,
            store_id=user.store_id,
            amount_override=_payment_amount_for_service(service),
        )
    except CircuitBreakerOpenError as exc:
        raise AppException(
            message=f"Proveedor de pagos temporalmente no disponible: {exc}",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="PAYMENT_PROVIDER_UNAVAILABLE",
        )
    except RuntimeError as exc:
        raise AppException(
            message=f"No se pudo crear el link de pago: {exc}",
            http_status=status.HTTP_502_BAD_GATEWAY,
            error_code="PAYMENT_LINK_CREATION_FAILED",
        )
    await db.commit()
    await db.refresh(payment)
    return _payment_preference_response(payment)


@router.post("/{appointment_id}/manual-confirm", response_model=PaymentResponse)
async def manual_confirm_payment(
    appointment_id: PublicIdPath,
    data: ManualPaymentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentResponse:
    _require_payment_manager(user)
    await _ensure_payments_feature_enabled(db, user)
    appointment, service = await _get_appointment_with_service(
        db, appointment_id, user.store_id
    )
    # El cobro manual (efectivo/WhatsApp) es por el precio que se congelo al
    # reservar, no por el precio de lista de hoy. Si el dueno indica un monto
    # explicito, manda ese; si no, cae al snapshot del turno y recien despues al
    # calculo por servicio (turnos historicos sin snapshot).
    amount = data.amount
    if amount is None and appointment.price_amount is not None:
        amount = appointment.price_amount
    amount = _payment_amount_for_service(service, amount)
    payment = await ensure_payment_preference(
        db,
        appointment=appointment,
        service=service,
        store_id=user.store_id,
        amount_override=amount,
        create_provider_link=False,
    )
    stamp_payment_from_status(
        payment,
        PaymentStatus.MANUAL_CONFIRMED.value,
        payload={"notes": data.notes} if data.notes else None,
    )
    sync_appointment_with_payment(appointment, payment.status)

    db.add(
        OutboxMessage(
            store_id=user.store_id,
            event_type="payment.manual_confirmed",
            payload={"appointment_id": appointment_id, "payment_id": payment.id},
        )
    )
    await db.commit()
    await db.refresh(payment)
    return _payment_response(payment)


@router.post("/{payment_id}/refund", response_model=PaymentResponse)
async def refund_payment(
    payment_id: PublicIdPath,
    data: RefundRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentResponse:
    _require_payment_admin(user)
    await _ensure_payments_feature_enabled(db, user)
    payment = await _get_payment_by_id(db, payment_id, user.store_id)
    # Solo se puede devolver plata que efectivamente entro. Reembolsar un pago
    # pendiente marcaria como devuelto un cobro que nunca existio.
    if payment.status not in {
        PaymentStatus.APPROVED.value,
        PaymentStatus.MANUAL_CONFIRMED.value,
    }:
        raise ValidationException(
            "Solo se pueden reembolsar pagos acreditados o confirmados manualmente"
        )
    refund_amount = data.amount if data.amount is not None else payment.amount
    if refund_amount <= 0 or refund_amount > payment.amount:
        raise ValidationException(
            "El importe a reembolsar debe ser mayor a cero y no superar lo cobrado"
        )
    # El monto historico del pago no se pisa: el reembolso queda en el payload.
    stamp_payment_from_status(
        payment,
        PaymentStatus.REFUNDED.value,
        payload={
            "reason": data.reason,
            "manual": data.manual,
            "refunded_amount": str(refund_amount),
        },
    )
    appointment_result = await db.execute(
        select(Appointment).where(
            Appointment.id == payment.appointment_id,
            Appointment.store_id == user.store_id,
        )
    )
    appointment = appointment_result.scalar_one_or_none()
    if appointment:
        sync_appointment_with_payment(appointment, payment.status)
    db.add(
        OutboxMessage(
            store_id=user.store_id,
            event_type="payment.refunded",
            payload={"payment_id": payment.id, "reason": data.reason},
        )
    )
    await db.commit()
    await db.refresh(payment)
    return _payment_response(payment)


@router.post("/webhooks/mercadopago")
async def mercadopago_webhook(
    request: Request,
    store_id: Annotated[str | None, Query(max_length=64)] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)
        # Un body invalido no puede tirar un 500: es trafico externo no confiable.
        try:
            payload = await request.json()
        except Exception as exc:
            raise WebhookException(message="Body de webhook invalido") from exc
        if not isinstance(payload, dict):
            raise WebhookException(message="Body de webhook invalido")
        resolved_store_id = await _validate_mercadopago_signature(
            db,
            payload=payload,
            request=request,
            store_reference=store_id,
        )
        payload = await enrich_mercadopago_webhook_payload(
            db,
            store_id=resolved_store_id,
            payload=payload,
        )

        event_id = _webhook_event_id(payload)

        existing = await db.execute(
            select(WebhookInbox).where(WebhookInbox.event_id == event_id)
        )
        inbox = existing.scalar_one_or_none()
        if inbox:
            if inbox.processed_at is not None:
                return {"success": True, "data": {"status": "already_processed"}}
            inbox.payload = payload
        else:
            inbox = WebhookInbox(
                store_id=resolved_store_id,
                provider="mercadopago",
                event_id=event_id,
                event_type=str(payload.get("type") or payload.get("topic") or ""),
                payload=payload,
            )
            db.add(inbox)

        # Si no pudimos resolver el pago (por ejemplo, porque la consulta a Mercado
        # Pago fallo y el webhook crudo no trae estado), dejamos el evento sin
        # procesar para que el worker del inbox lo reintente. Marcarlo aca perderia
        # el cobro de forma permanente.
        applied = await apply_mercadopago_webhook_payload(
            db, store_id=resolved_store_id, payload=payload
        )
        if applied:
            inbox.mark_processed()
        else:
            inbox.register_failure("No se pudo resolver el pago del webhook")
        await db.commit()
        return {"success": True, "data": {"received": True, "applied": applied}}
    finally:
        set_tenant_context(None, False)


@router.get("/outbox/stats", response_model=OutboxStatsResponse)
async def outbox_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OutboxStatsResponse:
    _require_payment_admin(user)
    await _ensure_payments_feature_enabled(db, user)
    pending = await _count_store_rows(
        db,
        OutboxMessage,
        OutboxMessage.store_id == user.store_id,
        OutboxMessage.processed_at.is_(None),
        OutboxMessage.error.is_(None),
    )
    pending_with_error = await _count_store_rows(
        db,
        OutboxMessage,
        OutboxMessage.store_id == user.store_id,
        OutboxMessage.processed_at.is_(None),
        OutboxMessage.error.is_not(None),
    )
    processed = await _count_store_rows(
        db,
        OutboxMessage,
        OutboxMessage.store_id == user.store_id,
        OutboxMessage.processed_at.is_not(None),
    )
    return OutboxStatsResponse(
        pending=pending,
        pending_with_error=pending_with_error,
        processed=processed,
    )


@router.get("/reconciliation/summary", response_model=ReconciliationSummaryResponse)
async def reconciliation_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationSummaryResponse:
    _require_payment_admin(user)
    await _ensure_payments_feature_enabled(db, user)

    pending_payments = int(
        (
            await db.scalar(
                _payment_status_count_query(user.store_id, PaymentStatus.PENDING.value)
            )
        )
        or 0
    )
    approved_payments = int(
        (
            await db.scalar(
                _payment_status_count_query(user.store_id, PaymentStatus.APPROVED.value)
            )
        )
        or 0
    )
    rejected_payments = int(
        (
            await db.scalar(
                _payment_status_count_query(user.store_id, PaymentStatus.REJECTED.value)
            )
        )
        or 0
    )
    manual_confirmed_payments = int(
        (
            await db.scalar(
                _payment_status_count_query(
                    user.store_id, PaymentStatus.MANUAL_CONFIRMED.value
                )
            )
        )
        or 0
    )
    refunded_payments = int(
        (
            await db.scalar(
                _payment_status_count_query(user.store_id, PaymentStatus.REFUNDED.value)
            )
        )
        or 0
    )
    total_pending_amount = Decimal(
        str(
            (
                await db.scalar(
                    _payment_status_sum_query(
                        user.store_id, PaymentStatus.PENDING.value
                    )
                )
            )
            or 0
        )
    )
    approved_amount = Decimal(
        str(
            await db.scalar(
                _payment_status_sum_query(user.store_id, PaymentStatus.APPROVED.value)
            )
            or 0
        )
    )
    manual_confirmed_amount = Decimal(
        str(
            await db.scalar(
                _payment_status_sum_query(
                    user.store_id, PaymentStatus.MANUAL_CONFIRMED.value
                )
            )
            or 0
        )
    )
    total_approved_amount = approved_amount + manual_confirmed_amount
    pending_webhooks = await _count_store_rows(
        db,
        WebhookInbox,
        WebhookInbox.store_id == user.store_id,
        WebhookInbox.processed_at.is_(None),
        WebhookInbox.error.is_(None),
    )
    failed_webhooks = await _count_store_rows(
        db,
        WebhookInbox,
        WebhookInbox.store_id == user.store_id,
        WebhookInbox.error.is_not(None),
    )
    pending_outbox = await _count_store_rows(
        db,
        OutboxMessage,
        OutboxMessage.store_id == user.store_id,
        OutboxMessage.processed_at.is_(None),
    )

    return ReconciliationSummaryResponse(
        pending_payments=pending_payments,
        approved_payments=approved_payments,
        rejected_payments=rejected_payments,
        manual_confirmed_payments=manual_confirmed_payments,
        refunded_payments=refunded_payments,
        total_pending_amount=total_pending_amount,
        total_approved_amount=total_approved_amount,
        pending_webhooks=pending_webhooks,
        failed_webhooks=failed_webhooks,
        pending_outbox=pending_outbox,
    )


@router.post("/outbox/process", response_model=OutboxProcessResponse)
async def process_outbox(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> OutboxProcessResponse:
    _require_payment_admin(user)
    await _ensure_payments_feature_enabled(db, user)
    result = await process_outbox_batch(db, store_id=user.store_id, limit=limit)
    return OutboxProcessResponse(**result)
