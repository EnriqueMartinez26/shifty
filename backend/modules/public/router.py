"""
Router Público del Turnero.

Rutas sin autenticación para reservas, OTP y autogestión del cliente.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import _apply_tenant_context, get_db, set_tenant_context
from core.feature_flags import is_store_feature_enabled
from core.idempotency import idempotency_guard, idempotency_release, idempotency_save
from core.rate_limit import enforce_rate_limit
from core.redis import get_redis
from core.validation import PUBLIC_ID_PATTERN, SLUG_PATTERN
from modules.appointments.availability import AvailabilityService
from modules.appointments.model import Appointment, AppointmentStatus
from modules.otp.service import OtpService
from modules.payments.service import ensure_payment_preference, service_requires_payment
from modules.public.repository import PublicRepository
from modules.public.schemas import (
    ClientAppointmentItem,
    ClientAppointmentsResponse,
    ClientCancelRequest,
    ClientRescheduleRequest,
    OtpRequestPayload,
    OtpVerifyPayload,
    PublicBookingCreate,
    PublicBookingResponse,
    PublicServiceResponse,
    PublicStaffResponse,
    PublicStoreResponse,
)
from modules.services.model import Service
from modules.staff.model import Staff

router = APIRouter(prefix="/public", tags=["Public Booking"])
PublicIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)]
PublicIdQuery = Annotated[str, Query(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)]
SlugPath = Annotated[str, Path(min_length=2, max_length=100, pattern=SLUG_PATTERN)]


def _public_booking_idempotency_key(data: PublicBookingCreate) -> str:
    raw_key = "|".join(
        [data.service_id, data.staff_id or "any", data.starts_at.isoformat(), data.client_phone]
    )
    return "public-" + hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def _bypass_rls(db: AsyncSession) -> None:
    set_tenant_context(None, is_admin=True)
    await _apply_tenant_context(db)


def _normalize_custom_field_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _validate_custom_fields(store, custom_fields: dict[str, str] | None) -> dict[str, str]:
    configured_fields = store.custom_client_fields or []
    configured_by_key = {
        field.get("key"): field
        for field in configured_fields
        if isinstance(field, dict) and field.get("key")
    }
    incoming = custom_fields or {}

    unknown_keys = [key for key in incoming if key not in configured_by_key]
    if unknown_keys:
        raise HTTPException(
            status_code=422,
            detail=f"Campos extra invalidos: {', '.join(sorted(unknown_keys))}",
        )

    normalized: dict[str, str] = {}
    for key, raw_value in incoming.items():
        value = _normalize_custom_field_value(raw_value)
        if len(value) > 500:
            raise HTTPException(
                status_code=422,
                detail=f"El campo extra '{key}' supera el maximo permitido",
            )

        field_config = configured_by_key[key]
        if field_config.get("type") == "select" and value:
            allowed_values = {
                str(option.get("value", "")).strip()
                for option in (field_config.get("options") or [])
                if isinstance(option, dict)
            }
            if allowed_values and value not in allowed_values:
                raise HTTPException(
                    status_code=422,
                    detail=f"Valor invalido para el campo '{field_config.get('label') or key}'",
                )
        normalized[key] = value

    missing_required = [
        field.get("label") or field.get("key")
        for field in configured_fields
        if field.get("required") and not normalized.get(field.get("key", ""), "").strip()
    ]
    if missing_required:
        raise HTTPException(
            status_code=422,
            detail=f"Faltan campos requeridos: {', '.join(missing_required)}",
        )

    return {key: value for key, value in normalized.items() if value}


@router.get("/stores/{slug}", response_model=PublicStoreResponse)
async def get_store_by_slug(slug: SlugPath, db: AsyncSession = Depends(get_db)):
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        store = await repo.get_store_by_slug(slug)
        if not store:
            raise HTTPException(status_code=404, detail="Negocio no encontrado")
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
            custom_client_fields=store.custom_client_fields,
            feature_flags=store.normalized_feature_flags,
        )
    finally:
        set_tenant_context(None, False)


@router.get("/services", response_model=list[PublicServiceResponse])
async def get_public_services(
    store_public_id: PublicIdQuery,
    db: AsyncSession = Depends(get_db),
):
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        store = await repo.get_store_by_public_id(store_public_id)
        if not store:
            raise HTTPException(status_code=404, detail="Negocio no encontrado")
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
                deposit_amount=float(service.deposit_amount) if getattr(service, "deposit_amount", None) is not None else None,
                color=service.color,
                image_url=service.image_url,
            )
            for service in services
        ]
    finally:
        set_tenant_context(None, False)


@router.get("/staff", response_model=list[PublicStaffResponse])
async def get_public_staff(
    store_public_id: Annotated[str | None, Query(max_length=64, pattern=PUBLIC_ID_PATTERN)] = None,
    service_id: Annotated[str | None, Query(max_length=64, pattern=PUBLIC_ID_PATTERN)] = None,
    db: AsyncSession = Depends(get_db),
):
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        store_id = None
        if store_public_id:
            store = await repo.get_store_by_public_id(store_public_id)
            if not store:
                raise HTTPException(status_code=404, detail="Negocio no encontrado")
            store_id = store.id

        if service_id:
            service = await repo.get_service_by_public_id(service_id)
            if not service:
                raise HTTPException(status_code=404, detail="Servicio no encontrado")
            if store_id is not None and service.store_id != store_id:
                raise HTTPException(status_code=404, detail="Servicio no encontrado en este negocio")
            store_id = service.store_id

        if store_id is None:
            raise HTTPException(status_code=400, detail="Debe indicar store_public_id o service_id")

        staff_members = await repo.get_staff(store_id, service_public_id=service_id)
        return [
            PublicStaffResponse(
                public_id=member.public_id,
                first_name=member.first_name or "",
                last_name=member.last_name or "",
                email=None,
                display_name=member.display_name,
                service_ids=member.service_ids or [svc.public_id for svc in member.services],
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
):
    from datetime import date as date_type

    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        store = await repo.get_store_by_public_id(store_public_id)
        if not store:
            raise HTTPException(status_code=404, detail="Negocio no encontrado")
        try:
            search_date = date_type.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Fecha inválida")
        return await AvailabilityService(db, redis).get_available_slots(
            store.id,
            service_id,
            search_date,
            force_all=force_all,
            hide_private_reasons=True,
        )
    finally:
        set_tenant_context(None, False)


@router.post("/otp/request")
async def request_public_otp(
    request: Request,
    data: OtpRequestPayload,
    db: AsyncSession = Depends(get_db),
):
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
            raise HTTPException(status_code=404, detail="Negocio no encontrado")
        return await OtpService(db).request_code(store_id=store.id, phone=data.phone, channel=data.channel)
    finally:
        set_tenant_context(None, False)


@router.post("/otp/verify")
async def verify_public_otp(
    request: Request,
    data: OtpVerifyPayload,
    db: AsyncSession = Depends(get_db),
):
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
            raise HTTPException(status_code=404, detail="Negocio no encontrado")
        return await OtpService(db).verify_code(store_id=store.id, phone=data.phone, code=data.code)
    finally:
        set_tenant_context(None, False)


@router.post("/appointments", response_model=PublicBookingResponse, status_code=status.HTTP_201_CREATED)
async def create_public_booking(
    request: Request,
    data: PublicBookingCreate,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
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
            return cached

        repo = PublicRepository(db)
        service = await repo.get_service_by_public_id(data.service_id)
        if not service:
            raise HTTPException(status_code=404, detail="Servicio no encontrado")

        if data.store_public_id:
            store = await repo.get_store_by_public_id(data.store_public_id)
            if not store:
                raise HTTPException(status_code=404, detail="Negocio no encontrado")
            if service.store_id != store.id:
                raise HTTPException(status_code=404, detail="Servicio no encontrado en este negocio")
            store_id = store.id
        else:
            store_id = service.store_id
            store = await repo.get_store_by_id(store_id)
            if not store:
                raise HTTPException(status_code=404, detail="Negocio no encontrado")

        if is_store_feature_enabled(store.feature_flags, "otp_booking"):
            is_verified = await OtpService(db).is_recently_verified(
                store_id=store_id,
                phone=data.client_phone,
            )
            if not is_verified:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Se requiere validar OTP antes de reservar",
                )

        normalized_custom_fields = _validate_custom_fields(store, data.custom_fields)
        payment_required = is_store_feature_enabled(store.feature_flags, "payments") and service_requires_payment(service)
        initial_status = (
            AppointmentStatus.PENDING_PAYMENT.value
            if payment_required
            else AppointmentStatus.CONFIRMED.value
            if is_store_feature_enabled(store.feature_flags, "otp_booking")
            else AppointmentStatus.PENDING.value
        )

        payment = None
        try:
            async with db.begin_nested():
                client = await repo.get_or_create_client(
                    store_id=store_id,
                    phone=data.client_phone,
                    name=data.client_name,
                    email=data.client_email,
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
                )
                if payment_required:
                    payment = await ensure_payment_preference(
                        db,
                        appointment=appointment,
                        service=service,
                        store_id=store_id,
                    )
        except ValueError as exc:
            await idempotency_release(idempotency_key, redis)
            raise HTTPException(status_code=409, detail=str(exc))

        await db.commit()
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
            payment_amount=float(payment.amount) if payment else None,
        )
        await idempotency_save(idempotency_key, response.model_dump(mode="json"), redis)
        return response
    except Exception:
        if idempotency_key:
            await idempotency_release(idempotency_key, redis)
        raise
    finally:
        set_tenant_context(None, False)


@router.get("/client/{store_public_id}/{phone}/appointments", response_model=ClientAppointmentsResponse)
async def get_client_appointments(
    request: Request,
    store_public_id: PublicIdPath,
    phone: Annotated[str, Path(min_length=6, max_length=30)],
    db: AsyncSession = Depends(get_db),
):
    import re

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
            raise HTTPException(status_code=404, detail="Negocio no encontrado")

        client = await repo.get_client_by_phone(store.id, phone)
        if not client:
            raise HTTPException(status_code=404, detail="No se encontraron turnos para ese número de teléfono")

        appointments = await repo.get_client_appointments(client.id, store.id)
        now = datetime.now(timezone.utc)
        cancellation_cutoff_hours = getattr(store, "cancellation_hours", 2)
        items = []
        for appt in appointments:
            current_status = AppointmentStatus(appt.status)
            is_upcoming = appt.starts_at > now
            hours_until = (appt.starts_at - now).total_seconds() / 3600
            can_cancel = (
                current_status in (AppointmentStatus.PENDING, AppointmentStatus.PENDING_PAYMENT, AppointmentStatus.CONFIRMED)
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
            client_name=client.first_name or "Cliente",
            client_phone=phone,
            appointments=items,
        )
    finally:
        set_tenant_context(None, False)


@router.patch("/client/appointments/{public_id}/cancel", response_model=PublicBookingResponse)
async def client_cancel_appointment(
    public_id: PublicIdPath,
    request: Request,
    data: ClientCancelRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    await enforce_rate_limit(
        request,
        "public:client:cancel",
        settings.RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE,
        subject=f"{public_id}:{data.phone}",
    )
    await _bypass_rls(db)
    try:
        repo = PublicRepository(db)
        appt_res = await db.execute(select(Appointment).where(Appointment.id == public_id))
        appointment = appt_res.scalar_one_or_none()
        if not appointment:
            raise HTTPException(status_code=404, detail="Turno no encontrado")

        client = await repo.get_client_by_phone(appointment.store_id, data.phone)
        if not client or client.id != appointment.client_id:
            raise HTTPException(status_code=403, detail="El teléfono no coincide con el titular del turno")

        store = await repo.get_store_by_id(appointment.store_id)
        cancellation_hours = getattr(store, "cancellation_hours", 2) if store else 2
        hours_until = (appointment.starts_at - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours_until < cancellation_hours:
            raise HTTPException(
                status_code=409,
                detail=f"Solo se puede cancelar con {cancellation_hours}h de anticipación",
            )

        appointment.apply_status_transition(AppointmentStatus.CANCELLED)
        await db.commit()
        await db.refresh(appointment)

        svc_res = await db.execute(select(Service).where(Service.id == appointment.service_id))
        service = svc_res.scalar_one_or_none()
        if service:
            cache_key = f"availability:{appointment.store_id}:{service.public_id}:{appointment.starts_at.date().isoformat()}"
            await redis.delete(cache_key)

        stf_res = await db.execute(select(Staff).where(Staff.id == appointment.staff_id))
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
            client_name=client.first_name or "Cliente",
            client_phone=data.phone,
            notes=appointment.notes,
            custom_fields=appointment.intake_answers or {},
        )
    finally:
        set_tenant_context(None, False)


@router.patch("/client/appointments/{public_id}/reschedule", response_model=PublicBookingResponse)
async def client_reschedule_appointment(
    public_id: PublicIdPath,
    request: Request,
    data: ClientRescheduleRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
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
            return cached

        appt_res = await db.execute(select(Appointment).where(Appointment.id == public_id))
        original = appt_res.scalar_one_or_none()
        if not original:
            raise HTTPException(status_code=404, detail="Turno no encontrado")

        client = await repo.get_client_by_phone(original.store_id, data.phone)
        if not client or client.id != original.client_id:
            raise HTTPException(status_code=403, detail="El teléfono no coincide con el titular del turno")

        svc_res = await db.execute(select(Service).where(Service.id == original.service_id))
        service = svc_res.scalar_one_or_none()
        if not service:
            raise HTTPException(status_code=404, detail="Servicio no encontrado")

        stf_res = await db.execute(select(Staff).where(Staff.id == original.staff_id))
        staff = stf_res.scalar_one_or_none()
        if not staff:
            raise HTTPException(status_code=404, detail="Profesional no encontrado")

        new_ends_at = data.new_starts_at + timedelta(minutes=service.duration_minutes)

        try:
            async with db.begin_nested():
                await db.execute(select(Staff).where(Staff.id == staff.id).with_for_update())
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
                    raise HTTPException(status_code=409, detail="El nuevo horario ya está ocupado")

                original.apply_status_transition(AppointmentStatus.CANCELLED)
                new_appointment = Appointment(
                    store_id=original.store_id,
                    staff_id=original.staff_id,
                    service_id=original.service_id,
                    client_id=original.client_id,
                    starts_at=data.new_starts_at,
                    ends_at=new_ends_at,
                    duration_minutes=service.duration_minutes,
                    client_name=client.first_name or client.email,
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

        for key_date in {original.starts_at.date(), data.new_starts_at.date()}:
            await redis.delete(f"availability:{original.store_id}:{service.public_id}:{key_date.isoformat()}")

        response = PublicBookingResponse(
            public_id=new_appointment.public_id,
            service_id=service.public_id,
            service_name=service.name,
            staff_id=staff.public_id,
            staff_name=staff.display_name,
            starts_at=new_appointment.starts_at,
            ends_at=new_appointment.ends_at,
            status=new_appointment.status,
            client_name=client.first_name or "Cliente",
            client_phone=data.phone,
            notes=new_appointment.notes,
            custom_fields=new_appointment.intake_answers or {},
        )
        await idempotency_save(data.idempotency_key, response.model_dump(mode="json"), redis)
        return response
    finally:
        set_tenant_context(None, False)
