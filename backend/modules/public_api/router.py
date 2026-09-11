"""
Router Público del Turnero.

Rutas sin autenticación para reservas, OTP y autogestión del cliente.
"""

import hashlib
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated

import structlog
from fastapi import Depends, Path, Query, Request, status
from core.router import CanonicalAPIRouter
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.circuit_breaker import CircuitBreakerOpenError
from core.config import settings
from core.database import _apply_tenant_context, get_db, set_tenant_context
from core.exceptions import (
    AppException,
    BookingNoticeException,
    AppointmentConflictException,
    AppointmentNotFoundException,
    OTPException,
    PermissionDeniedException,
    ServiceNotFoundException,
    StaffNotFoundException,
    StoreNotFoundException,
    ValidationException,
)
from core.feature_flags import is_store_feature_enabled
from core.availability_cache import invalidate_availability
from core.idempotency import idempotency_guard, idempotency_release, idempotency_save
from core.rate_limit import enforce_rate_limit
from core.redis import get_redis
from core.validation import PUBLIC_ID_PATTERN
from modules.appointments.availability import AvailabilityService
from modules.appointments.guards import (
    reject_cancellation_while_awaiting_payment,
)
from modules.appointments.model import Appointment, AppointmentStatus
from modules.billing.service import store_is_suspended
from modules.otp.service import OtpService
from modules.payments.deposit_rules import (
    UNKNOWN_HISTORY,
    ClientHistory,
    DepositDecision,
    DepositRules,
    decide_deposit,
)
from modules.payments.service import ensure_payment_preference
from modules.payments.model import OutboxMessage, Payment, PaymentStatus
from modules.notifications.model import NotificationType
from modules.notifications.tasks import (
    build_client_details,
    enqueue_confirmation_email,
    enqueue_registration_email,
)
from modules.promotions.model import PromotionRedemption
from modules.promotions.service import quote_promotion, redeem_promotion
from modules.public_api.repository import PublicRepository
from modules.public_api.schemas import (
    ClientAppointmentItem,
    ClientAppointmentsResponse,
    ClientCancelRequest,
    ClientRescheduleRequest,
    OtpRequestPayload,
    OtpVerifyPayload,
    PublicBookingCreate,
    PublicBookingResponse,
    PublicDepositPreviewResponse,
    PublicPromotionPreviewResponse,
    PublicPaymentStatusResponse,
    PublicServiceResponse,
    PublicStaffResponse,
    PublicStoreResponse,
)
from modules.services.model import Service
from modules.staff.model import Staff
from modules.stores.model import Store
from modules.stores.schemas import StoreCustomField
from modules.waitlist.events import publish_slot_released
from modules.waitlist.offers import mark_booked

router = CanonicalAPIRouter(prefix="/public", tags=["Public Booking"])
logger = structlog.get_logger()
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]
PublicIdQuery = Annotated[
    str, Query(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]
# El slug canonico es minuscula, pero la URL publica la tipean humanos:
# "MiBarberia" tiene que resolver a "mibarberia", no dar 422.
SlugPath = Annotated[
    str, Path(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,98}$")
]


def _payment_hold_deadline(starts_at: datetime) -> datetime:
    """Hasta cuando se retiene el slot de un turno que espera el pago de la seña.

    Nunca mas alla del horario del turno. Devuelve el valor con la misma
    conciencia de zona horaria que ``starts_at`` para no mezclar naive y aware.
    """
    is_naive = starts_at.tzinfo is None
    reference = starts_at.replace(tzinfo=timezone.utc) if is_naive else starts_at
    deadline = min(
        datetime.now(timezone.utc) + timedelta(minutes=settings.PAYMENT_HOLD_MINUTES),
        reference,
    )
    return deadline.replace(tzinfo=None) if is_naive else deadline


def _public_booking_idempotency_key(data: PublicBookingCreate) -> str:
    raw_key = "|".join(
        [
            data.service_id,
            data.staff_id or "any",
            data.starts_at.isoformat(),
            data.client_phone,
        ]
    )
    return "public-" + hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def _bypass_rls(db: AsyncSession) -> None:
    set_tenant_context(None, is_admin=True)
    await _apply_tenant_context(db)


async def _revert_failed_booking(db: AsyncSession, appointment_id: str) -> None:
    """Compensa un booking cuyo link de pago fallo DESPUES del commit.

    Como el link de Mercado Pago se genera fuera de la transaccion que sostiene
    el lock (fix del DoS), el turno + Payment ya estan persistidos cuando MP
    falla. Se revierten para no dejar el slot retenido ni un pago sin link, y
    para que un reintento pueda crear el turno limpio. Reemplaza al rollback del
    savepoint que existia cuando el HTTP corria dentro de la transaccion.
    """
    await db.execute(
        delete(PromotionRedemption).where(
            PromotionRedemption.appointment_id == appointment_id
        )
    )
    await db.execute(delete(Payment).where(Payment.appointment_id == appointment_id))
    await db.execute(delete(Appointment).where(Appointment.id == appointment_id))
    await db.commit()


def _normalize_custom_field_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _validate_custom_fields(
    store: Store, custom_fields: dict[str, str] | None
) -> dict[str, str]:
    configured_fields = store.custom_client_fields or []
    configured_by_key = {
        field.get("key"): field
        for field in configured_fields
        if isinstance(field, dict) and field.get("key")
    }
    incoming = custom_fields or {}

    unknown_keys = [key for key in incoming if key not in configured_by_key]
    if unknown_keys:
        raise ValidationException(
            message=f"Campos extra invalidos: {', '.join(sorted(unknown_keys))}"
        )

    normalized: dict[str, str] = {}
    for key, raw_value in incoming.items():
        value = _normalize_custom_field_value(raw_value)
        if len(value) > 500:
            raise ValidationException(
                message=f"El campo extra '{key}' supera el maximo permitido"
            )

        field_config = configured_by_key[key]
        if field_config.get("type") == "select" and value:
            allowed_values = {
                str(option.get("value", "")).strip()
                for option in (field_config.get("options") or [])
                if isinstance(option, dict)
            }
            if allowed_values and value not in allowed_values:
                raise ValidationException(
                    message=f"Valor invalido para el campo '{field_config.get('label') or key}'"
                )
        normalized[key] = value

    missing_required = [
        str(field.get("label") or field.get("key") or "")
        for field in configured_fields
        if field.get("required")
        and not normalized.get(field.get("key", ""), "").strip()
    ]
    if missing_required:
        raise ValidationException(
            message=f"Faltan campos requeridos: {', '.join(missing_required)}"
        )

    return {key: value for key, value in normalized.items() if value}


async def _require_recent_client_otp(
    db: AsyncSession, *, store_id: str, phone: str
) -> None:
    is_verified = await OtpService(db).is_recently_verified(
        store_id=store_id, phone=phone
    )
    if not is_verified:
        raise OTPException(
            message="Se requiere validar OTP antes de autogestionar turnos",
            error_code="OTP_VERIFICATION_REQUIRED",
            http_status=status.HTTP_403_FORBIDDEN,
        )


def _now_compatible_with(value: datetime) -> datetime:
    now = datetime.now(timezone.utc)
    return now if value.tzinfo else now.replace(tzinfo=None)


def _resolve_payment_requirement(
    payment_method: str,
    payments_enabled: bool,
    deposit_amount: Decimal,
    deposit_mode: str,
    allow_manual_coordination: bool,
) -> bool:
    # Responde una sola vez "con el metodo pedido y estos datos de tienda/
    # servicio, hace falta pagar la sena para reservar" en vez de repetir la
    # misma combinacion de 5 variables en tres ifs distintos. Puede levantar
    # ValidationException si el payment_method pedido no es viable.
    viable = payments_enabled and deposit_amount > 0
    mandatory_online = (
        viable and deposit_mode == "required" and not allow_manual_coordination
    )

    if payment_method == "mercadopago":
        if deposit_amount <= 0:
            raise ValidationException(
                "Este servicio no tiene una seña configurada para Mercado Pago"
            )
        if not payments_enabled:
            raise ValidationException(
                "La tienda no tiene habilitados los cobros con Mercado Pago"
            )
        return True
    if payment_method == "manual":
        if mandatory_online:
            raise ValidationException(
                "Este servicio requiere pagar la seña con Mercado Pago para reservar"
            )
        return False
    return viable  # "auto"


@router.get("/stores/{slug}", response_model=PublicStoreResponse)
async def get_store_by_slug(
    slug: SlugPath, db: AsyncSession = Depends(get_db)
) -> PublicStoreResponse:
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        store = await repo.get_store_by_slug(slug.lower())
        if not store:
            raise StoreNotFoundException(identifier=slug)
        # Tienda con la suscripcion suspendida: la vitrina publica desaparece
        # (mismo 404 que una tienda inexistente, sin revelar el motivo).
        if await store_is_suspended(db, store.id):
            raise StoreNotFoundException(identifier=slug)
        return PublicStoreResponse(
            public_id=store.public_id,
            name=store.name,
            slug=store.slug,
            business_type=store.business_type,
            logo_url=store.logo_url,
            primary_color=store.primary_color,
            cancellation_hours=store.cancellation_hours,
            description=store.description,
            cover_url=store.cover_url,
            whatsapp_number=store.whatsapp_number,
            website_url=store.website_url,
            allow_manual_coordination=store.allow_manual_coordination,
            deposit_policy=store.deposit_policy,
            custom_client_fields=[
                StoreCustomField.model_validate(field)
                for field in (store.custom_client_fields or [])
            ],
            # Solo los flags que la vitrina publica necesita (pago online y si
            # exige OTP). No exponer a anonimos capacidades internas de la
            # tienda (ledger, reportes avanzados, calendario nuevo).
            feature_flags={
                flag: bool(store.normalized_feature_flags.get(flag, False))
                for flag in ("payments", "otp_booking")
            },
        )
    finally:
        set_tenant_context(None, False)


@router.get("/services", response_model=list[PublicServiceResponse])
async def get_public_services(
    store_public_id: PublicIdQuery,
    db: AsyncSession = Depends(get_db),
) -> list[PublicServiceResponse]:
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        store = await repo.get_store_by_public_id(store_public_id)
        if not store:
            raise StoreNotFoundException(identifier=store_public_id)
        services = await repo.get_services(store.id)
        return [
            PublicServiceResponse(
                public_id=service.public_id,
                name=service.name,
                description=service.description,
                duration_minutes=service.duration_minutes,
                price=float(service.price),
                deposit_mode=getattr(service, "deposit_mode", "none") or "none",
                deposit_type=getattr(service, "deposit_type", "percent") or "percent",
                deposit_amount=float(service.deposit_amount)
                if service.deposit_amount is not None
                else None,
                color=service.color,
                image_url=service.image_url,
            )
            for service in services
        ]
    finally:
        set_tenant_context(None, False)


@router.get("/staff", response_model=list[PublicStaffResponse])
async def get_public_staff(
    store_public_id: Annotated[
        str | None, Query(max_length=64, pattern=PUBLIC_ID_PATTERN)
    ] = None,
    service_id: Annotated[
        str | None, Query(max_length=64, pattern=PUBLIC_ID_PATTERN)
    ] = None,
    db: AsyncSession = Depends(get_db),
) -> list[PublicStaffResponse]:
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        store_id = None
        if store_public_id:
            store = await repo.get_store_by_public_id(store_public_id)
            if not store:
                raise StoreNotFoundException(identifier=store_public_id)
            store_id = store.id

        if service_id:
            service = await repo.get_service_by_public_id(service_id)
            if not service:
                raise ServiceNotFoundException(identifier=service_id)
            if store_id is not None and service.store_id != store_id:
                raise ServiceNotFoundException(identifier=service_id)
            store_id = service.store_id

        if store_id is None:
            raise ValidationException("Debe indicar store_public_id o service_id")

        staff_members = await repo.get_staff(store_id, service_public_id=service_id)
        return [
            PublicStaffResponse(
                public_id=member.public_id,
                kind=getattr(member, "kind", None) or "person",
                first_name=member.first_name or "",
                last_name=member.last_name or "",
                email=None,
                display_name=member.display_name,
                service_ids=member.service_ids
                or [svc.public_id for svc in member.services],
            )
            for member in staff_members
        ]
    finally:
        set_tenant_context(None, False)


@router.get("/availability")
async def get_public_availability(
    store_public_id: PublicIdQuery,
    service_id: PublicIdQuery,
    date: Annotated[str, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")],
    force_all: Annotated[bool, Query()] = False,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> list[object]:
    from datetime import date as date_type

    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        store = await repo.get_store_by_public_id(store_public_id)
        if not store:
            raise StoreNotFoundException(identifier=store_public_id)
        try:
            search_date = date_type.fromisoformat(date)
        except ValueError:
            raise ValidationException("Fecha inválida")
        return list(
            await AvailabilityService(db, redis).get_available_slots(
                store.id,
                service_id,
                search_date,
                force_all=force_all,
                hide_private_reasons=True,
            )
        )
    finally:
        set_tenant_context(None, False)


def _decide(
    service: Service,
    store: Store,
    *,
    price: Decimal,
    starts_at: datetime,
    history: ClientHistory,
    now: datetime | None = None,
) -> DepositDecision:
    now = now or datetime.now(timezone.utc)
    return decide_deposit(
        service,
        price=price,
        notice=starts_at - now,
        rules=DepositRules.from_store(store),
        history=history,
    )


@router.get("/deposit/preview", response_model=PublicDepositPreviewResponse)
async def preview_public_deposit(
    request: Request,
    store_public_id: PublicIdQuery,
    service_id: PublicIdQuery,
    starts_at: datetime,
    client_phone: Annotated[str | None, Query(min_length=6, max_length=30)] = None,
    promotion_code: Annotated[str | None, Query(min_length=3, max_length=30)] = None,
    db: AsyncSession = Depends(get_db),
) -> PublicDepositPreviewResponse:
    """La sena real antes de confirmar: misma regla que el alta.

    Sin esto el front inferia "hay sena" desde los campos crudos del servicio
    y divergia en cuanto la tienda configuraba un recargo.

    El historial del cliente SOLO entra si ese telefono paso por OTP en esta
    tienda: sin esa guarda el endpoint era un oraculo anonimo que decia, por
    telefono, si era cliente y si tenia ausencias. 2026-09-11.
    """
    telefono = re.sub(r"[\s\-\(\)\+]", "", client_phone) if client_phone else ""
    await enforce_rate_limit(
        request,
        "public:deposit:preview",
        settings.RATE_LIMIT_PUBLIC_READ_PER_MINUTE,
        subject=f"{store_public_id}:{telefono}",
    )
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        store = await repo.get_store_by_public_id(store_public_id)
        if not store:
            raise StoreNotFoundException(identifier=store_public_id)
        service = await repo.get_service_by_public_id(service_id)
        if not service or service.store_id != store.id:
            raise ServiceNotFoundException(identifier=service_id)

        price = Decimal(str(service.price or 0))
        if promotion_code:
            _promotion, quote, _error = await quote_promotion(
                db, store_id=store.id, service=service, code=promotion_code
            )
            if quote:
                price = quote.final_amount
        history = UNKNOWN_HISTORY
        if telefono and await OtpService(db).is_recently_verified(
            store_id=store.id, phone=telefono
        ):
            history = await repo.get_client_history(store.id, telefono)
        starts_at_utc = (
            starts_at if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc)
        )
        decision = _decide(
            service, store, price=price, starts_at=starts_at_utc, history=history
        )
        payments_enabled = is_store_feature_enabled(store.feature_flags, "payments")
        return PublicDepositPreviewResponse(
            amount=float(decision.amount),
            base_amount=float(decision.base_amount),
            extra_percent=decision.extra_percent,
            reasons=list(decision.reasons),
            price=float(price),
            payments_enabled=payments_enabled,
            online_payment_mandatory=bool(
                payments_enabled
                and decision.amount > 0
                and (getattr(service, "deposit_mode", "none") or "none") == "required"
                and not store.allow_manual_coordination
            ),
        )
    finally:
        set_tenant_context(None, False)


@router.get("/promotions/preview", response_model=PublicPromotionPreviewResponse)
async def preview_public_promotion(
    store_public_id: PublicIdQuery,
    service_id: PublicIdQuery,
    code: Annotated[str, Query(min_length=3, max_length=30)],
    db: AsyncSession = Depends(get_db),
) -> PublicPromotionPreviewResponse:
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        store = await repo.get_store_by_public_id(store_public_id)
        if not store:
            raise StoreNotFoundException(identifier=store_public_id)
        service = await repo.get_service_by_public_id(service_id)
        if not service or service.store_id != store.id:
            raise ServiceNotFoundException(identifier=service_id)

        _promotion, quote, error = await quote_promotion(
            db,
            store_id=store.id,
            service=service,
            code=code,
        )
        if not quote:
            raise ValidationException(error or "Promocion invalida")

        return PublicPromotionPreviewResponse(
            code=quote.code,
            title=quote.title,
            promotion_type=quote.promotion_type,
            base_amount=float(quote.base_amount),
            discount_amount=float(quote.discount_amount),
            final_amount=float(quote.final_amount),
        )
    finally:
        set_tenant_context(None, False)


@router.post("/otp/request")
async def request_public_otp(
    request: Request,
    data: OtpRequestPayload,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await enforce_rate_limit(
        request,
        "public:otp:request",
        settings.RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE,
        subject=f"{data.store_public_id}:{data.phone}",
    )
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        store = await repo.get_store_by_public_id(data.store_public_id)
        if not store:
            raise StoreNotFoundException(identifier=data.store_public_id)
        return await OtpService(db).request_code(
            store_id=store.id,
            phone=data.phone,
            channel=data.channel,
            email=str(data.email) if data.email else None,
            store_name=store.name,
        )
    finally:
        set_tenant_context(None, False)


@router.post("/otp/verify")
async def verify_public_otp(
    request: Request,
    data: OtpVerifyPayload,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await enforce_rate_limit(
        request,
        "public:otp:verify",
        settings.RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE,
        subject=f"{data.store_public_id}:{data.phone}",
    )
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        store = await repo.get_store_by_public_id(data.store_public_id)
        if not store:
            raise StoreNotFoundException(identifier=data.store_public_id)
        return await OtpService(db).verify_code(
            store_id=store.id, phone=data.phone, code=data.code
        )
    finally:
        set_tenant_context(None, False)


@router.post(
    "/appointments",
    response_model=PublicBookingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_public_booking(
    request: Request,
    data: PublicBookingCreate,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> PublicBookingResponse:
    await enforce_rate_limit(
        request,
        "public:booking:create",
        settings.RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE,
        subject=f"{data.client_phone}:{data.service_id}",
    )
    idempotency_key: str | None = None
    await _bypass_rls(db)
    try:
        idempotency_key = data.idempotency_key or _public_booking_idempotency_key(data)
        cached = await idempotency_guard(idempotency_key, redis)
        if cached:
            return PublicBookingResponse.model_validate(cached)

        repo = PublicRepository(db)
        service = await repo.get_service_by_public_id(data.service_id)
        if not service:
            raise ServiceNotFoundException(identifier=data.service_id)

        if data.store_public_id:
            store = await repo.get_store_by_public_id(data.store_public_id)
            if not store:
                raise StoreNotFoundException(identifier=data.store_public_id)
            if service.store_id != store.id:
                raise ServiceNotFoundException(identifier=data.service_id)
            store_id = store.id
        else:
            store_id = service.store_id
            store = await repo.get_store_by_id(store_id)
            if not store:
                raise StoreNotFoundException(identifier=str(store_id))

        # Antelacion minima. El flujo admin ya la validaba, pero el booking
        # publico solo la aplicaba al *mostrar* slots, no al crearlos: un POST
        # directo podia agendar en el pasado o dentro de la ventana bloqueada.
        notice_hours = getattr(store, "min_booking_notice_hours", 2) or 0
        starts_at_utc = (
            data.starts_at
            if data.starts_at.tzinfo
            else data.starts_at.replace(tzinfo=timezone.utc)
        )
        if starts_at_utc < datetime.now(timezone.utc) + timedelta(hours=notice_hours):
            raise BookingNoticeException(notice_hours)

        # El OTP es lo unico que prueba que quien reserva es dueno del
        # telefono: sin el, los datos de contacto de esta peticion no pisan
        # los del cliente que ya existe (ver get_or_create_client).
        phone_verified = await OtpService(db).is_recently_verified(
            store_id=store_id,
            phone=data.client_phone,
        )
        if is_store_feature_enabled(store.feature_flags, "otp_booking"):
            if not phone_verified:
                raise OTPException(
                    message="Se requiere validar OTP antes de reservar",
                    error_code="OTP_VERIFICATION_REQUIRED",
                    http_status=status.HTTP_403_FORBIDDEN,
                )

        normalized_custom_fields = _validate_custom_fields(store, data.custom_fields)
        base_service_price = Decimal(str(service.price or 0))
        preview_promotion_quote = None
        if data.promotion_code:
            _promotion, preview_promotion_quote, preview_error = await quote_promotion(
                db,
                store_id=store_id,
                service=service,
                code=data.promotion_code,
            )
            if not preview_promotion_quote:
                raise ValidationException(preview_error or "Promocion invalida")

        discounted_service_price = (
            preview_promotion_quote.final_amount
            if preview_promotion_quote
            else base_service_price
        )
        # La regla de sena se evalua UNA vez (misma antelacion, mismo
        # historial) y el resultado viaja hasta el pago y la respuesta. Antes se
        # recalculaba tres veces con `now` distinto. El historial es una sola
        # consulta agregada, antes del lock.
        # Mismo criterio que el preview: un telefono sin verificar no trae el
        # historial de nadie, ni para mostrar ni para cobrar. Si no, quien
        # tipea el telefono de otro hereda (o le carga) sus recargos.
        history = (
            await repo.get_client_history(store_id, data.client_phone)
            if phone_verified
            else UNKNOWN_HISTORY
        )
        deposit = _decide(
            service,
            store,
            price=discounted_service_price,
            starts_at=starts_at_utc,
            history=history,
        )
        deposit_amount = deposit.amount
        payments_enabled = is_store_feature_enabled(store.feature_flags, "payments")
        payment_required = _resolve_payment_requirement(
            payment_method=data.payment_method,
            payments_enabled=payments_enabled,
            deposit_amount=deposit_amount,
            deposit_mode=getattr(service, "deposit_mode", "none") or "none",
            allow_manual_coordination=store.allow_manual_coordination,
        )
        initial_status = (
            AppointmentStatus.PENDING_PAYMENT.value
            if payment_required
            else AppointmentStatus.PENDING.value
        )

        payment = None
        promotion_quote = None
        try:
            async with db.begin_nested():
                client = await repo.get_or_create_client(
                    store_id=store_id,
                    phone=data.client_phone,
                    name=data.client_name,
                    email=data.client_email,
                    adopt_contact=phone_verified,
                )
                appointment, service, staff = await repo.create_appointment(
                    store_id=store_id,
                    service_public_id=data.service_id,
                    staff_public_id=data.staff_id,
                    starts_at=data.starts_at,
                    client=client,
                    notes=data.notes,
                    intake_answers=normalized_custom_fields,
                    idempotency_key=idempotency_key,
                    initial_status=initial_status,
                    buffer_minutes=store.buffer_minutes or 0,
                    price_amount=discounted_service_price,
                    client_email=str(data.client_email) if data.client_email else None,
                )
                # Un turno esperando la seña retiene el slot solo por una ventana
                # corta: si no se paga, vuelve a estar disponible enseguida en vez
                # de bloquear la agenda hasta la hora del turno. La coordinacion
                # manual si retiene hasta el horario, porque la confirma la tienda.
                if payment_required:
                    appointment.expires_at = _payment_hold_deadline(
                        appointment.starts_at
                    )
                else:
                    appointment.expires_at = appointment.starts_at
                if data.accepts_terms:
                    appointment.terms_accepted_at = datetime.now(timezone.utc)
                if data.promotion_code:
                    try:
                        promotion_quote = await redeem_promotion(
                            db,
                            store_id=store_id,
                            appointment_id=appointment.id,
                            client=client,
                            service=service,
                            code=data.promotion_code,
                        )
                    except ValueError as exc:
                        raise ValidationException(str(exc))
                if payment_required:
                    # Misma regla (antelacion e historial), dos precios: el de
                    # lista para mostrar el descuento y el final para cobrar.
                    payable_before_discount = _decide(
                        service,
                        store,
                        price=base_service_price,
                        starts_at=starts_at_utc,
                        history=history,
                    ).amount
                    final_decision = (
                        _decide(
                            service,
                            store,
                            price=promotion_quote.final_amount,
                            starts_at=starts_at_utc,
                            history=history,
                        )
                        if promotion_quote
                        else deposit
                    )
                    payable_after_discount = final_decision.amount
                    # Dentro de la transaccion (que sostiene el lock FOR UPDATE
                    # del staff) solo se crea el Payment PENDING con link
                    # placeholder: la llamada HTTP a Mercado Pago se hace DESPUES
                    # del commit, con el lock ya soltado (ver mas abajo), para no
                    # serializar reservas ni agotar el pool ante latencia de MP.
                    payment = await ensure_payment_preference(
                        db,
                        appointment=appointment,
                        service=service,
                        store_id=store_id,
                        amount_override=payable_after_discount,
                        original_amount=payable_before_discount,
                        discount_amount=max(
                            Decimal("0.00"),
                            payable_before_discount - payable_after_discount,
                        ),
                        promotion_code=promotion_quote.code
                        if promotion_quote
                        else None,
                        create_provider_link=False,
                        deposit_rule=final_decision.snapshot(),
                    )
                else:
                    # El pago se coordina por fuera, asi que la tienda tiene que
                    # confirmar el turno a mano cuando reciba la transferencia.
                    db.add(
                        OutboxMessage(
                            store_id=store_id,
                            event_type=NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value,
                            payload={
                                "appointment_id": appointment.id,
                                "client_name": data.client_name,
                                "service_name": service.name,
                            },
                        )
                    )
        except ValueError as exc:
            await idempotency_release(idempotency_key, redis)
            raise AppException(
                message=str(exc), http_status=409, error_code="APPOINTMENT_CONFLICT"
            )
        except CircuitBreakerOpenError as exc:
            await idempotency_release(idempotency_key, redis)
            raise AppException(
                message=f"Proveedor de pagos temporalmente no disponible: {exc}",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_code="PAYMENT_PROVIDER_UNAVAILABLE",
            )
        except RuntimeError as exc:
            await idempotency_release(idempotency_key, redis)
            raise AppException(
                message=f"No se pudo iniciar el cobro online: {exc}",
                http_status=status.HTTP_502_BAD_GATEWAY,
                error_code="PAYMENT_LINK_CREATION_FAILED",
            )

        await db.commit()
        # El cupo dejo de estar libre: la disponibilidad publica lo refleja ya
        # (antes la reserva publica no invalidaba nada y el slot seguia
        # "available" hasta cinco minutos).
        await invalidate_availability(redis, store_id, appointment.starts_at)

        # El turno y el Payment PENDING ya estan persistidos y el lock FOR UPDATE
        # del staff quedo soltado. Recien ahora se hace la llamada HTTP a Mercado
        # Pago para el link real: fuera de la transaccion, sin retener el lock ni
        # serializar otras reservas. Si MP falla, el turno queda en
        # PENDING_PAYMENT y su hold expira solo; un reintento (misma idempotency)
        # reusa el turno y reintenta el link.
        if payment_required and payment is not None:
            try:
                await ensure_payment_preference(
                    db,
                    appointment=appointment,
                    service=service,
                    store_id=store_id,
                    amount_override=payment.amount,
                    original_amount=payment.original_amount,
                    discount_amount=payment.discount_amount,
                    promotion_code=payment.promotion_code,
                    create_provider_link=True,
                )
                await db.commit()
            except CircuitBreakerOpenError as exc:
                await _revert_failed_booking(db, appointment.id)
                await idempotency_release(idempotency_key, redis)
                raise AppException(
                    message=f"Proveedor de pagos temporalmente no disponible: {exc}",
                    http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    error_code="PAYMENT_PROVIDER_UNAVAILABLE",
                )
            except RuntimeError as exc:
                await _revert_failed_booking(db, appointment.id)
                await idempotency_release(idempotency_key, redis)
                raise AppException(
                    message=f"No se pudo iniciar el cobro online: {exc}",
                    http_status=status.HTTP_502_BAD_GATEWAY,
                    error_code="PAYMENT_LINK_CREATION_FAILED",
                )

        # Aviso al cliente por mail (best-effort, fuera de la transaccion).
        # Antes la condicion exigia CONFIRMED y el turno nace PENDING o
        # PENDING_PAYMENT: nunca salia nada. Ahora "reserva registrada" al
        # crear, y "turno confirmado" solo si ya nacio confirmado.
        detalles_cliente = build_client_details(appointment, service, staff, store)
        if appointment.status == AppointmentStatus.CONFIRMED.value:
            await enqueue_confirmation_email(
                email=appointment.client_email, details=detalles_cliente
            )
        else:
            await enqueue_registration_email(
                email=appointment.client_email, details=detalles_cliente
            )
        response = PublicBookingResponse(
            public_id=appointment.public_id,
            service_id=service.public_id,
            service_name=service.name,
            staff_id=staff.public_id,
            staff_name=staff.display_name,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            status=appointment.status,
            client_name=data.client_name,
            client_phone=data.client_phone,
            notes=data.notes,
            custom_fields=appointment.intake_answers or normalized_custom_fields,
            payment_required=payment_required,
            payment_status=payment.status if payment else None,
            payment_link=payment.payment_link if payment else None,
            payment_public_id=payment.id if payment else None,
            # Sin pago online se informa la misma decision que se evaluo arriba
            # (el precio final ya trae la promo cuando la hubo).
            payment_amount=float(payment.amount if payment else deposit.amount),
            promotion_code=promotion_quote.code if promotion_quote else None,
            service_price=float(base_service_price),
            discount_amount=float(promotion_quote.discount_amount)
            if promotion_quote
            else 0.0,
            final_price=float(promotion_quote.final_amount)
            if promotion_quote
            else float(base_service_price),
        )
        # Recien con el turno firme (incluido el link de pago) se cierra la
        # entrada de lista de espera: cerrarla antes la perdia si el link de
        # Mercado Pago fallaba y el turno se revertia. Best-effort: no puede
        # deshacer una reserva ya hecha.
        try:
            if await mark_booked(
                db,
                store_id=store_id,
                client_phone=data.client_phone,
                service_id=service.id,
                starts_at=appointment.starts_at,
            ):
                await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.warning("waitlist_mark_booked_failed", error_type=type(exc).__name__)

        await idempotency_save(idempotency_key, response.model_dump(mode="json"), redis)
        return response
    except Exception:
        if idempotency_key:
            await idempotency_release(idempotency_key, redis)
        raise
    finally:
        set_tenant_context(None, False)


@router.get(
    "/payments/{payment_public_id}/status",
    response_model=PublicPaymentStatusResponse,
)
async def get_public_payment_status(
    payment_public_id: PublicIdPath,
    request: Request,
    store_public_id: PublicIdQuery,
    db: AsyncSession = Depends(get_db),
) -> PublicPaymentStatusResponse:
    await enforce_rate_limit(
        request,
        "public:payment:status",
        settings.RATE_LIMIT_PUBLIC_READ_PER_MINUTE,
        subject=f"{store_public_id}:{payment_public_id}",
    )
    await _bypass_rls(db)
    try:
        result = await db.execute(
            select(Payment, Appointment)
            .join(Appointment, Appointment.id == Payment.appointment_id)
            .join(Store, Store.id == Payment.store_id)
            .where(
                Payment.id == payment_public_id,
                Store.public_id == store_public_id,
                Payment.store_id == Appointment.store_id,
            )
        )
        row = result.first()
        if not row:
            raise AppointmentNotFoundException(public_id=payment_public_id)
        payment, appointment = row
        return PublicPaymentStatusResponse(
            payment_public_id=payment.id,
            appointment_public_id=appointment.public_id,
            payment_status=payment.status,
            appointment_status=appointment.status,
            amount=float(payment.amount),
            currency=payment.currency,
            starts_at=appointment.starts_at,
        )
    finally:
        set_tenant_context(None, False)


@router.get(
    "/client/{store_public_id}/{phone}/appointments",
    response_model=ClientAppointmentsResponse,
)
async def get_client_appointments(
    request: Request,
    store_public_id: PublicIdPath,
    phone: Annotated[str, Path(min_length=6, max_length=30)],
    db: AsyncSession = Depends(get_db),
) -> ClientAppointmentsResponse:
    phone = re.sub(r"[\s\-\(\)\+]", "", phone)
    await enforce_rate_limit(
        request,
        "public:client:appointments",
        settings.RATE_LIMIT_PUBLIC_READ_PER_MINUTE,
        subject=f"{store_public_id}:{phone}",
    )
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        store = await repo.get_store_by_public_id(store_public_id)
        if not store:
            raise StoreNotFoundException(identifier=store_public_id)

        await _require_recent_client_otp(db, store_id=store.id, phone=phone)

        client = await repo.get_client_by_phone(store.id, phone)
        if not client:
            raise AppException(
                message="No se encontraron turnos para ese número de teléfono",
                http_status=404,
                error_code="CLIENT_APPOINTMENTS_NOT_FOUND",
            )

        appointments = await repo.get_client_appointments(client.id, store.id)
        cancellation_cutoff_hours = getattr(store, "cancellation_hours", 2)
        items = []
        for appt in appointments:
            now = _now_compatible_with(appt.starts_at)
            current_status = AppointmentStatus(appt.status)
            is_upcoming = appt.starts_at > now
            hours_until = (appt.starts_at - now).total_seconds() / 3600
            can_cancel = (
                current_status
                in (
                    AppointmentStatus.PENDING,
                    AppointmentStatus.PENDING_PAYMENT,
                    AppointmentStatus.CONFIRMED,
                )
                and is_upcoming
                and hours_until >= cancellation_cutoff_hours
            )
            items.append(
                ClientAppointmentItem(
                    public_id=appt.public_id,
                    service_name=appt.service.name,
                    staff_name=appt.staff.display_name,
                    starts_at=appt.starts_at,
                    ends_at=appt.ends_at,
                    status=appt.status,
                    notes=appt.notes,
                    custom_fields=appt.intake_answers or {},
                    can_cancel=can_cancel,
                    can_reschedule=can_cancel,
                )
            )

        return ClientAppointmentsResponse(
            client_name=client.full_name or "Cliente",
            client_phone=phone,
            appointments=items,
        )
    finally:
        set_tenant_context(None, False)


@router.patch(
    "/client/appointments/{public_id}/cancel", response_model=PublicBookingResponse
)
async def client_cancel_appointment(
    public_id: PublicIdPath,
    request: Request,
    data: ClientCancelRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> PublicBookingResponse:
    await enforce_rate_limit(
        request,
        "public:client:cancel",
        settings.RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE,
        subject=f"{public_id}:{data.phone}",
    )
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        # Lock del turno antes de transicionarlo (TOCTOU).
        appt_res = await db.execute(
            select(Appointment).where(Appointment.id == public_id).with_for_update()
        )
        appointment = appt_res.scalar_one_or_none()
        if not appointment:
            raise AppointmentNotFoundException(public_id=public_id)

        client = await repo.get_client_by_phone(appointment.store_id, data.phone)
        if not client or client.id != appointment.client_id:
            raise PermissionDeniedException(
                action="El teléfono no coincide con el titular del turno"
            )

        await _require_recent_client_otp(
            db, store_id=appointment.store_id, phone=data.phone
        )

        # Mismo guard que la via administrativa: un turno con cobro vivo solo se
        # suelta por release(), que vence antes la preferencia en Mercado Pago.
        reject_cancellation_while_awaiting_payment(appointment)

        store = await repo.get_store_by_id(appointment.store_id)
        cancellation_hours = getattr(store, "cancellation_hours", 2) if store else 2
        hours_until = (
            appointment.starts_at - _now_compatible_with(appointment.starts_at)
        ).total_seconds() / 3600
        if hours_until < cancellation_hours:
            raise AppException(
                message=f"Solo se puede cancelar con {cancellation_hours}h de anticipación",
                http_status=409,
                error_code="CANCELLATION_WINDOW_EXPIRED",
            )

        appointment.apply_status_transition(AppointmentStatus.CANCELLED)
        publish_slot_released(
            db,
            store_id=appointment.store_id,
            staff_id=appointment.staff_id,
            service_id=appointment.service_id,
            appointment_id=appointment.id,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            reason="client_cancelled",
        )
        # La tienda se entera de que le cancelaron: antes el cliente cancelaba
        # y el dueno solo lo notaba mirando la agenda.
        servicio_cancelado = await db.execute(
            select(Service).where(Service.id == appointment.service_id)
        )
        db.add(
            OutboxMessage(
                store_id=appointment.store_id,
                event_type=NotificationType.APPOINTMENT_CANCELLED_BY_CLIENT.value,
                payload={
                    "appointment_id": appointment.id,
                    "client_name": client.full_name or "Un cliente",
                    "service_name": getattr(
                        servicio_cancelado.scalar_one_or_none(), "name", ""
                    ),
                    "starts_at": appointment.starts_at.isoformat(),
                },
            )
        )
        await db.commit()
        await db.refresh(appointment)

        svc_res = await db.execute(
            select(Service).where(Service.id == appointment.service_id)
        )
        service = svc_res.scalar_one_or_none()
        await invalidate_availability(
            redis, appointment.store_id, appointment.starts_at
        )

        stf_res = await db.execute(
            select(Staff).where(Staff.id == appointment.staff_id)
        )
        staff = stf_res.scalar_one_or_none()
        return PublicBookingResponse(
            public_id=appointment.public_id,
            service_id=service.public_id if service else str(appointment.service_id),
            service_name=service.name if service else "",
            staff_id=staff.public_id if staff else str(appointment.staff_id),
            staff_name=staff.display_name if staff else "",
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            status=appointment.status,
            client_name=client.full_name or "Cliente",
            client_phone=data.phone,
            notes=appointment.notes,
            custom_fields=appointment.intake_answers or {},
        )
    finally:
        set_tenant_context(None, False)


@router.patch(
    "/client/appointments/{public_id}/reschedule", response_model=PublicBookingResponse
)
async def client_reschedule_appointment(
    public_id: PublicIdPath,
    request: Request,
    data: ClientRescheduleRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> PublicBookingResponse:
    await enforce_rate_limit(
        request,
        "public:client:reschedule",
        settings.RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE,
        subject=f"{public_id}:{data.phone}",
    )
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        cached = await idempotency_guard(data.idempotency_key, redis)
        if cached:
            return PublicBookingResponse.model_validate(cached)

        # Lock del turno: reprogramar lo cancela, y sin lock dos requests
        # concurrentes pueden partir del mismo estado origen.
        appt_res = await db.execute(
            select(Appointment).where(Appointment.id == public_id).with_for_update()
        )
        original = appt_res.scalar_one_or_none()
        if not original:
            raise AppointmentNotFoundException(public_id=public_id)

        # Titularidad + OTP ANTES de cualquier chequeo que revele estado del
        # turno: sin esto, quien solo conozca el public_id sabria si esta
        # esperando pago (fuga menor de estado).
        client = await repo.get_client_by_phone(original.store_id, data.phone)
        if not client or client.id != original.client_id:
            raise PermissionDeniedException(
                action="El teléfono no coincide con el titular del turno"
            )

        await _require_recent_client_otp(
            db, store_id=original.store_id, phone=data.phone
        )

        # Reprogramar cancela el turno original: le corresponde el mismo guard.
        reject_cancellation_while_awaiting_payment(original)

        # Un turno con pago acreditado no se reprograma desde el cliente: el
        # Payment quedaria huerfano apuntando al turno cancelado y el nuevo
        # apareceria como impago. Que lo maneje la tienda.
        paid_res = await db.execute(
            select(Payment.id).where(
                Payment.appointment_id == original.id,
                Payment.status.in_(
                    [
                        PaymentStatus.APPROVED.value,
                        PaymentStatus.MANUAL_CONFIRMED.value,
                    ]
                ),
            )
        )
        if paid_res.scalar_one_or_none() is not None:
            raise AppException(
                message=(
                    "Este turno ya tiene un pago registrado; contactá a la tienda "
                    "para reprogramarlo."
                ),
                http_status=status.HTTP_409_CONFLICT,
                error_code="PAID_APPOINTMENT_RESCHEDULE_DENIED",
            )

        svc_res = await db.execute(
            select(Service).where(Service.id == original.service_id)
        )
        service = svc_res.scalar_one_or_none()
        if not service:
            raise ServiceNotFoundException(identifier=str(original.service_id))

        stf_res = await db.execute(select(Staff).where(Staff.id == original.staff_id))
        staff = stf_res.scalar_one_or_none()
        if not staff:
            raise StaffNotFoundException(identifier=str(original.staff_id))

        new_starts_utc = (
            data.new_starts_at
            if data.new_starts_at.tzinfo
            else data.new_starts_at.replace(tzinfo=timezone.utc)
        )
        new_ends_at = data.new_starts_at + timedelta(minutes=service.duration_minutes)

        # El nuevo horario debe respetar las MISMAS reglas que una reserva nueva:
        # antelacion minima, agenda del profesional y bloqueos. Antes solo se
        # validaba el solapamiento, asi que un cliente podia moverse a un horario
        # fuera de agenda, sobre un franco, o dentro de la ventana de antelacion.
        store = await repo.get_store_by_id(original.store_id)
        notice_hours = getattr(store, "min_booking_notice_hours", 2) or 0
        if new_starts_utc < datetime.now(timezone.utc) + timedelta(hours=notice_hours):
            raise BookingNoticeException(notice_hours)
        if not await repo._staff_has_schedule_for_slot(
            staff.id, data.new_starts_at, new_ends_at
        ):
            raise AppException(
                message="El profesional no atiende en ese horario",
                http_status=status.HTTP_409_CONFLICT,
                error_code="OUT_OF_SCHEDULE",
            )
        if await repo._staff_has_overlapping_block(
            staff.id, data.new_starts_at, new_ends_at
        ):
            raise AppException(
                message="Ese horario esta bloqueado en la agenda",
                http_status=status.HTTP_409_CONFLICT,
                error_code="SCHEDULE_BLOCKED",
            )

        try:
            async with db.begin_nested():
                await db.execute(
                    select(Staff).where(Staff.id == staff.id).with_for_update()
                )
                conflict_res = await db.execute(
                    select(Appointment)
                    .where(
                        Appointment.staff_id == staff.id,
                        Appointment.status.in_(
                            [
                                AppointmentStatus.PENDING.value,
                                AppointmentStatus.PENDING_PAYMENT.value,
                                AppointmentStatus.CONFIRMED.value,
                            ]
                        ),
                        Appointment.id != original.id,
                        Appointment.starts_at < new_ends_at,
                        Appointment.ends_at > data.new_starts_at,
                    )
                    .limit(1)
                )
                if conflict_res.scalar_one_or_none():
                    raise AppointmentConflictException()

                original.apply_status_transition(AppointmentStatus.CANCELLED)
                publish_slot_released(
                    db,
                    store_id=original.store_id,
                    staff_id=original.staff_id,
                    service_id=original.service_id,
                    appointment_id=original.id,
                    starts_at=original.starts_at,
                    ends_at=original.ends_at,
                    reason="client_rescheduled",
                )
                new_appointment = Appointment(
                    store_id=original.store_id,
                    staff_id=original.staff_id,
                    service_id=original.service_id,
                    client_id=original.client_id,
                    starts_at=data.new_starts_at,
                    ends_at=new_ends_at,
                    duration_minutes=service.duration_minutes,
                    # Preservar el precio congelado del turno original.
                    price_amount=original.price_amount,
                    client_name=client.full_name or client.email,
                    client_email=client.email,
                    client_phone=client.phone,
                    notes=original.notes,
                    intake_answers=original.intake_answers or {},
                    idempotency_key=data.idempotency_key,
                )
                db.add(new_appointment)
                await db.flush()
        except Exception:
            await idempotency_release(data.idempotency_key, redis)
            raise

        await db.commit()
        await db.refresh(new_appointment)

        await invalidate_availability(
            redis, original.store_id, original.starts_at, data.new_starts_at
        )

        response = PublicBookingResponse(
            public_id=new_appointment.public_id,
            service_id=service.public_id,
            service_name=service.name,
            staff_id=staff.public_id,
            staff_name=staff.display_name,
            starts_at=new_appointment.starts_at,
            ends_at=new_appointment.ends_at,
            status=new_appointment.status,
            client_name=client.full_name or "Cliente",
            client_phone=data.phone,
            notes=new_appointment.notes,
            custom_fields=new_appointment.intake_answers or {},
        )
        await idempotency_save(
            data.idempotency_key, response.model_dump(mode="json"), redis
        )
        return response
    except Exception:
        await idempotency_release(data.idempotency_key, redis)
        raise
    finally:
        set_tenant_context(None, False)
