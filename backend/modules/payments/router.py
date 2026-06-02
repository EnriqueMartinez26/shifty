from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.crypto import encrypt_secret
from core.database import _apply_tenant_context, get_db, set_tenant_context
from core.feature_flags import is_store_feature_enabled
from core.validation import PUBLIC_ID_PATTERN
from modules.appointments.model import Appointment
from modules.auth.dependencies import get_current_user
from modules.payments.model import OutboxMessage, Payment, PaymentGatewayConfig, PaymentStatus, WebhookInbox
from modules.payments.schemas import (
    GatewayConfigResponse,
    GatewayConfigUpsert,
    ManualPaymentRequest,
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

router = APIRouter(prefix="/payments", tags=["Payments"])
PublicIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)]


def _require_payment_manager(user: User) -> None:
    if user.role not in (UserRole.ADMIN, UserRole.STAFF) and not user.is_global_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenes permiso para gestionar pagos")


def _require_payment_admin(user: User) -> None:
    if user.role != UserRole.ADMIN and not user.is_global_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo administradores pueden ejecutar esta accion")


async def _ensure_payments_feature_enabled(db: AsyncSession, user: User) -> None:
    result = await db.execute(select(Store).where(Store.id == user.store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    if not is_store_feature_enabled(store.feature_flags, "payments"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La funcionalidad de pagos no esta habilitada para esta tienda",
        )


async def _get_payment_by_id(db: AsyncSession, payment_id: str, store_id: str) -> Payment:
    result = await db.execute(select(Payment).where(Payment.id == payment_id, Payment.store_id == store_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
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


async def _resolve_store_for_webhook(db: AsyncSession, store_reference: str | None) -> tuple[str, PaymentGatewayConfig]:
    if not store_reference:
        raise HTTPException(status_code=400, detail="store_id invalido para webhook")

    config_result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.store_id == store_reference,
            PaymentGatewayConfig.provider == "mercadopago",
        )
    )
    config = config_result.scalar_one_or_none()
    if config:
        return store_reference, config

    store_result = await db.execute(select(Store).where(Store.public_id == store_reference))
    store = store_result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=400, detail="store_id invalido para webhook")

    config_result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.store_id == store.id,
            PaymentGatewayConfig.provider == "mercadopago",
        )
    )
    config = config_result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=400, detail="Webhook secret no configurado")
    return store.id, config


async def _validate_mercadopago_signature(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    request: Request,
    store_reference: str | None,
) -> str:
    resolved_store_id, config = await _resolve_store_for_webhook(db, store_reference)
    secret = config.webhook_secret or settings.MERCADOPAGO_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(status_code=400, detail="Webhook secret no configurado")

    signature_header = request.headers.get("x-signature", "")
    request_id = request.headers.get("x-request-id", "")
    if not signature_header or not request_id:
        raise HTTPException(status_code=400, detail="Headers de firma faltantes")

    parsed = _parse_signature_header(signature_header)
    if not parsed:
        raise HTTPException(status_code=400, detail="Header x-signature invalido")

    ts, received_v1 = parsed
    data_id = _resolve_webhook_data_id(payload, request.query_params.get("data.id"))
    if not data_id:
        raise HTTPException(status_code=400, detail="No se pudo resolver data.id del webhook")

    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    expected_v1 = hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_v1.lower(), expected_v1.lower()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Firma de webhook invalida")

    return resolved_store_id


@router.get("/gateway-config", response_model=GatewayConfigResponse)
async def get_gateway_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_payment_manager(user)
    await _ensure_payments_feature_enabled(db, user)
    result = await db.execute(
        select(PaymentGatewayConfig).where(PaymentGatewayConfig.store_id == user.store_id).limit(1)
    )
    config = result.scalar_one_or_none()
    if not config:
        return GatewayConfigResponse(provider="mercadopago", configured=False)
    return GatewayConfigResponse(
        provider=config.provider,
        configured=True,
        public_key=config.public_key,
        access_token_masked="********",
    )


@router.put("/gateway-config", response_model=GatewayConfigResponse)
async def upsert_gateway_config(
    data: GatewayConfigUpsert,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_payment_admin(user)
    await _ensure_payments_feature_enabled(db, user)
    result = await db.execute(
        select(PaymentGatewayConfig).where(
            PaymentGatewayConfig.store_id == user.store_id,
            PaymentGatewayConfig.provider == data.provider,
        )
    )
    config = result.scalar_one_or_none()
    encrypted_access_token = encrypt_secret(data.access_token) or data.access_token
    if not config:
        config = PaymentGatewayConfig(
            store_id=user.store_id,
            provider=data.provider,
            encrypted_access_token=encrypted_access_token,
            public_key=data.public_key,
            webhook_secret=data.webhook_secret,
        )
        db.add(config)
    else:
        config.encrypted_access_token = encrypted_access_token
        config.public_key = data.public_key
        config.webhook_secret = data.webhook_secret
    await db.commit()
    await db.refresh(config)
    return GatewayConfigResponse(
        provider=config.provider,
        configured=True,
        public_key=config.public_key,
        access_token_masked="********",
    )


@router.post("/preferences/{appointment_id}", response_model=PaymentPreferenceResponse)
async def create_payment_preference(
    appointment_id: PublicIdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_payment_manager(user)
    await _ensure_payments_feature_enabled(db, user)

    result = await db.execute(
        select(Appointment, Service)
        .join(Service, Appointment.service_id == Service.id)
        .where(Appointment.id == appointment_id, Appointment.store_id == user.store_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    appointment, service = row

    payment_result = await db.execute(
        select(Payment).where(Payment.appointment_id == appointment.id, Payment.store_id == user.store_id)
    )
    payment = payment_result.scalar_one_or_none()
    if not payment:
        amount = Decimal(str(service.price))
        payment = Payment(
            store_id=user.store_id,
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
                store_id=user.store_id,
                event_type="payment.preference.created",
                payload={"appointment_id": appointment.id, "payment_id": payment.id},
            )
        )
        await db.commit()
        await db.refresh(payment)

    return PaymentPreferenceResponse(
        payment_public_id=payment.id,
        appointment_id=payment.appointment_id,
        amount=payment.amount,
        currency=payment.currency,
        preference_id=payment.preference_id,
        payment_link=payment.payment_link,
        status=payment.status,
    )


@router.post("/{appointment_id}/manual-confirm", response_model=PaymentResponse)
async def manual_confirm_payment(
    appointment_id: PublicIdPath,
    data: ManualPaymentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_payment_manager(user)
    await _ensure_payments_feature_enabled(db, user)
    payment_result = await db.execute(
        select(Payment).where(Payment.appointment_id == appointment_id, Payment.store_id == user.store_id)
    )
    payment = payment_result.scalar_one_or_none()
    if not payment:
        appointment_result = await db.execute(
            select(Appointment, Service)
            .join(Service, Appointment.service_id == Service.id)
            .where(Appointment.id == appointment_id, Appointment.store_id == user.store_id)
        )
        row = appointment_result.first()
        if not row:
            raise HTTPException(status_code=404, detail="Turno no encontrado")
        _, service = row
        payment = Payment(
            store_id=user.store_id,
            appointment_id=appointment_id,
            amount=data.amount if data.amount is not None else Decimal(str(service.price)),
            currency="ARS",
            status=PaymentStatus.MANUAL_CONFIRMED.value,
            paid_at=datetime.now(timezone.utc),
            raw_payload={"notes": data.notes} if data.notes else None,
        )
        db.add(payment)
        await db.flush()
    else:
        if data.amount is not None:
            payment.amount = data.amount
        payment.status = PaymentStatus.MANUAL_CONFIRMED.value
        payment.paid_at = datetime.now(timezone.utc)
        payment.raw_payload = {"notes": data.notes} if data.notes else payment.raw_payload

    db.add(
        OutboxMessage(
            store_id=user.store_id,
            event_type="payment.manual_confirmed",
            payload={"appointment_id": appointment_id, "payment_id": payment.id},
        )
    )
    await db.commit()
    await db.refresh(payment)
    return PaymentResponse(
        public_id=payment.id,
        appointment_id=payment.appointment_id,
        amount=payment.amount,
        currency=payment.currency,
        status=payment.status,
        paid_at=payment.paid_at,
    )


@router.post("/{payment_id}/refund", response_model=PaymentResponse)
async def refund_payment(
    payment_id: PublicIdPath,
    data: RefundRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_payment_admin(user)
    await _ensure_payments_feature_enabled(db, user)
    payment = await _get_payment_by_id(db, payment_id, user.store_id)
    if data.amount is not None:
        payment.amount = data.amount
    payment.status = PaymentStatus.REFUNDED.value
    payment.raw_payload = {"reason": data.reason, "manual": data.manual}
    db.add(
        OutboxMessage(
            store_id=user.store_id,
            event_type="payment.refunded",
            payload={"payment_id": payment.id, "reason": data.reason},
        )
    )
    await db.commit()
    await db.refresh(payment)
    return PaymentResponse(
        public_id=payment.id,
        appointment_id=payment.appointment_id,
        amount=payment.amount,
        currency=payment.currency,
        status=payment.status,
        paid_at=payment.paid_at,
    )


@router.post("/webhooks/mercadopago")
async def mercadopago_webhook(
    request: Request,
    store_id: Annotated[str | None, Query(max_length=64)] = None,
    db: AsyncSession = Depends(get_db),
):
    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)
        payload = await request.json()
        resolved_store_id = await _validate_mercadopago_signature(
            db,
            payload=payload,
            request=request,
            store_reference=store_id,
        )

        event_id = str(payload.get("id") or payload.get("data", {}).get("id") or payload.get("resource") or "")
        if not event_id:
            raise HTTPException(status_code=400, detail="Webhook sin identificador")
        event_id = f"mercadopago:{event_id}"

        existing = await db.execute(select(WebhookInbox).where(WebhookInbox.event_id == event_id))
        inbox = existing.scalar_one_or_none()
        if not inbox:
            inbox = WebhookInbox(
                store_id=resolved_store_id,
                provider="mercadopago",
                event_id=event_id,
                event_type=str(payload.get("type") or payload.get("topic") or ""),
                payload=payload,
            )
            db.add(inbox)
            await db.commit()
        return {"success": True}
    finally:
        set_tenant_context(None, False)


@router.get("/outbox/stats", response_model=OutboxStatsResponse)
async def outbox_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_payment_admin(user)
    await _ensure_payments_feature_enabled(db, user)
    pending = await db.scalar(
        select(func.count()).select_from(OutboxMessage).where(
            OutboxMessage.store_id == user.store_id,
            OutboxMessage.processed_at.is_(None),
            OutboxMessage.error.is_(None),
        )
    )
    pending_with_error = await db.scalar(
        select(func.count()).select_from(OutboxMessage).where(
            OutboxMessage.store_id == user.store_id,
            OutboxMessage.processed_at.is_(None),
            OutboxMessage.error.is_not(None),
        )
    )
    processed = await db.scalar(
        select(func.count()).select_from(OutboxMessage).where(
            OutboxMessage.store_id == user.store_id,
            OutboxMessage.processed_at.is_not(None),
        )
    )
    return OutboxStatsResponse(
        pending=int(pending or 0),
        pending_with_error=int(pending_with_error or 0),
        processed=int(processed or 0),
    )


@router.get("/reconciliation/summary", response_model=ReconciliationSummaryResponse)
async def reconciliation_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_payment_admin(user)
    await _ensure_payments_feature_enabled(db, user)

    def _count(status_value: str):
        return select(func.count()).select_from(Payment).where(
            Payment.store_id == user.store_id,
            Payment.status == status_value,
        )

    def _sum(status_value: str):
        return select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.store_id == user.store_id,
            Payment.status == status_value,
        )

    pending_payments = int((await db.scalar(_count(PaymentStatus.PENDING.value))) or 0)
    approved_payments = int((await db.scalar(_count(PaymentStatus.APPROVED.value))) or 0)
    rejected_payments = int((await db.scalar(_count(PaymentStatus.REJECTED.value))) or 0)
    manual_confirmed_payments = int((await db.scalar(_count(PaymentStatus.MANUAL_CONFIRMED.value))) or 0)
    refunded_payments = int((await db.scalar(_count(PaymentStatus.REFUNDED.value))) or 0)
    total_pending_amount = Decimal(str((await db.scalar(_sum(PaymentStatus.PENDING.value))) or 0))
    total_approved_amount = Decimal(
        str(
            ((await db.scalar(_sum(PaymentStatus.APPROVED.value))) or 0)
            + ((await db.scalar(_sum(PaymentStatus.MANUAL_CONFIRMED.value))) or 0)
        )
    )
    pending_webhooks = int(
        (await db.scalar(
            select(func.count()).select_from(WebhookInbox).where(
                WebhookInbox.store_id == user.store_id,
                WebhookInbox.processed_at.is_(None),
                WebhookInbox.error.is_(None),
            )
        ))
        or 0
    )
    failed_webhooks = int(
        (await db.scalar(
            select(func.count()).select_from(WebhookInbox).where(
                WebhookInbox.store_id == user.store_id,
                WebhookInbox.error.is_not(None),
            )
        ))
        or 0
    )
    pending_outbox = int(
        (await db.scalar(
            select(func.count()).select_from(OutboxMessage).where(
                OutboxMessage.store_id == user.store_id,
                OutboxMessage.processed_at.is_(None),
            )
        ))
        or 0
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
):
    _require_payment_admin(user)
    await _ensure_payments_feature_enabled(db, user)
    result = await db.execute(
        select(OutboxMessage)
        .where(OutboxMessage.store_id == user.store_id, OutboxMessage.processed_at.is_(None))
        .order_by(OutboxMessage.created_at.asc())
        .limit(limit)
    )
    messages = list(result.scalars().all())
    now = datetime.now(timezone.utc)
    for message in messages:
        message.processed_at = now
        message.error = None
    await db.commit()
    return OutboxProcessResponse(processed=len(messages), failed=0, inspected=len(messages))
