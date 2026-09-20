"""
Router Público del Turnero.

Rutas sin autenticación para reservas, OTP y autogestión del cliente.
"""

import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

import structlog
from fastapi import Depends, Path, Query, Request, status
from core.router import CanonicalAPIRouter
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db, tenant_bypass
from core.exceptions import (
    AppException,
    AppointmentNotFoundException,
    ServiceNotFoundException,
    StoreNotFoundException,
    ValidationException,
)
from core.feature_flags import is_store_feature_enabled
from core.idempotency import idempotency_guard, idempotency_release, idempotency_save
from core.rate_limit import enforce_rate_limit
from core.redis import get_redis
from core.validation import PUBLIC_ID_PATTERN
from modules.appointments.availability import AvailabilityService
from modules.appointments.model import Appointment, AppointmentStatus
from modules.billing.service import store_is_suspended
from modules.notifications.tasks import enqueue_otp_email
from modules.otp.service import OtpService
from modules.payments.deposit_rules import (
    UNKNOWN_HISTORY,
)
from modules.payments.model import Payment
from modules.promotions.service import quote_promotion
from modules.public_api.repository import PublicRepository
from modules.public_api.service import (
    PublicBookingService,
    decide,
    now_compatible_with as _now_compatible_with,
    require_recent_client_otp as _require_recent_client_otp,
)
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
from modules.stores.model import Store
from modules.stores.schemas import StoreCustomField

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


@router.get("/stores/{slug}", response_model=PublicStoreResponse)
async def get_store_by_slug(
    slug: SlugPath, db: AsyncSession = Depends(get_db)
) -> PublicStoreResponse:
    async with tenant_bypass(db):
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


@router.get("/services", response_model=list[PublicServiceResponse])
async def get_public_services(
    store_public_id: PublicIdQuery,
    db: AsyncSession = Depends(get_db),
) -> list[PublicServiceResponse]:
    async with tenant_bypass(db):
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
    async with tenant_bypass(db):
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

    async with tenant_bypass(db):
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
    async with tenant_bypass(db):
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
        decision = decide(
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


@router.get("/promotions/preview", response_model=PublicPromotionPreviewResponse)
async def preview_public_promotion(
    store_public_id: PublicIdQuery,
    service_id: PublicIdQuery,
    code: Annotated[str, Query(min_length=3, max_length=30)],
    db: AsyncSession = Depends(get_db),
) -> PublicPromotionPreviewResponse:
    async with tenant_bypass(db):
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
    async with tenant_bypass(db):
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
            # AUD2-B4-06: a la cola, no a un BackgroundTask. El
            # BackgroundTask no salia del proceso: el SMTP corria dentro de
            # la misma llamada ASGI y retenia el slot hasta 10 s por pedido,
            # sin rastro durable ante un reinicio.
            schedule_dispatch=enqueue_otp_email,
        )


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
    async with tenant_bypass(db):
        repo = PublicRepository(db)
        store = await repo.get_store_by_public_id(data.store_public_id)
        if not store:
            raise StoreNotFoundException(identifier=data.store_public_id)
        return await OtpService(db).verify_code(
            store_id=store.id, phone=data.phone, code=data.code
        )


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
    """Reserva desde el portal. La transaccion es de ``PublicBookingService``.

    Aca queda HTTP: rate limit, bypass de tenant (el mismo alcance de antes:
    todo el caso de uso) e idempotencia (reserva, liberacion ante cualquier
    error y replay). B1-12.
    """
    await enforce_rate_limit(
        request,
        "public:booking:create",
        settings.RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE,
        subject=f"{data.client_phone}:{data.service_id}",
    )
    idempotency_key: str | None = None
    async with tenant_bypass(db):
        try:
            idempotency_key = data.idempotency_key or _public_booking_idempotency_key(
                data
            )
            cached = await idempotency_guard(idempotency_key, redis)
            if cached:
                return PublicBookingResponse.model_validate(cached)
            response = await PublicBookingService(db, redis).book(data, idempotency_key)
            await idempotency_save(
                idempotency_key, response.model_dump(mode="json"), redis
            )
            return response
        except Exception:
            if idempotency_key:
                await idempotency_release(idempotency_key, redis)
            raise


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
    async with tenant_bypass(db):
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
    async with tenant_bypass(db):
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
    """El cliente cancela su turno; la transaccion es del service (B1-12)."""
    await enforce_rate_limit(
        request,
        "public:client:cancel",
        settings.RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE,
        subject=f"{public_id}:{data.phone}",
    )
    async with tenant_bypass(db):
        return await PublicBookingService(db, redis).cancel_by_client(public_id, data)


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
    """El cliente reprograma su turno; la transaccion es del service (B1-12).

    Aca quedan el rate limit, el bypass de tenant (mismo alcance que antes) y
    la idempotencia: reserva antes del lock, liberacion ante cualquier error y
    replay.
    """
    await enforce_rate_limit(
        request,
        "public:client:reschedule",
        settings.RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE,
        subject=f"{public_id}:{data.phone}",
    )
    async with tenant_bypass(db):
        try:
            cached = await idempotency_guard(data.idempotency_key, redis)
            if cached:
                return PublicBookingResponse.model_validate(cached)
            response = await PublicBookingService(db, redis).reschedule_by_client(
                public_id, data
            )
            await idempotency_save(
                data.idempotency_key, response.model_dump(mode="json"), redis
            )
            return response
        except Exception:
            await idempotency_release(data.idempotency_key, redis)
            raise
