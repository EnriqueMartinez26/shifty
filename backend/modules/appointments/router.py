"""
Router de Turnos.

Responsabilidad única: recibir requests HTTP, delegar al AppointmentService
y serializar la respuesta. Sin lógica de negocio.
"""

from datetime import date as date_type
from typing import Annotated, AsyncGenerator, List, Optional, cast

from fastapi import Depends, Path, Query, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from core.cache import CacheInvalidator
from core.circuit_breaker import CircuitBreakerOpenError
from core.exceptions import AppException, AppointmentNotFoundException
from core.router import CanonicalAPIRouter
from core.database import _apply_tenant_context, get_db, set_tenant_context
from core.idempotency import idempotency_guard, idempotency_release, idempotency_save
from core.redis import get_redis
from core.roles import STORE_MANAGERS, require_roles
from core.validation import PUBLIC_ID_PATTERN
from modules.appointments.availability import AvailabilityService
from modules.appointments.model import Appointment, AppointmentStatus
from modules.appointments.schemas import (
    AppointmentCreate,
    AppointmentFilterParams,
    AppointmentListItem,
    AppointmentNotesStaffUpdate,
    AppointmentReschedule,
    AppointmentResponse,
    AppointmentSearchResponse,
    AppointmentSearchResult,
)
from modules.appointments.service import AppointmentBookPayload, AppointmentService
from modules.auth.dependencies import get_current_user, get_optional_current_user
from modules.audit.model import AuditAction
from modules.audit.repository import AuditRepository
from modules.payments.model import OutboxMessage, Payment, PaymentStatus
from modules.payments.service import (
    expire_mercadopago_preference,
    stamp_payment_from_status,
)

# NOTA: use public_api as the stable runtime import path for public booking data access.
from modules.public_api.repository import PublicRepository
from modules.users.model import User, UserRole

router = CanonicalAPIRouter(prefix="/appointments", tags=["Appointments"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]
PublicIdQuery = Annotated[
    str, Query(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


# ---------------------------------------------------------------------------
# Helpers de inyección
# ---------------------------------------------------------------------------

from core.uow import AsyncSqlAlchemyUnitOfWork


async def get_uow(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[AsyncSqlAlchemyUnitOfWork, None]:
    uow = AsyncSqlAlchemyUnitOfWork(db)
    async with uow:
        yield uow


def get_appointment_service(
    uow: AsyncSqlAlchemyUnitOfWork = Depends(get_uow),
    redis: Redis = Depends(get_redis),
) -> AppointmentService:
    return AppointmentService(uow=uow, cache=cast(CacheInvalidator, redis))


def _to_appointment_response(appointment: Appointment) -> AppointmentResponse:
    service = appointment.service
    staff = appointment.staff
    return AppointmentResponse(
        public_id=appointment.public_id,
        service_id=service.public_id if service else str(appointment.service_id),
        staff_id=staff.public_id if staff else str(appointment.staff_id),
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        status=AppointmentStatus(appointment.status),
        notes=appointment.notes,
        notes_staff=appointment.notes_staff,
        intake_answers=appointment.intake_answers or {},
        cancelled_at=appointment.cancelled_at,
        completed_at=appointment.completed_at,
    )


# ---------------------------------------------------------------------------
# Agenda diaria
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[AppointmentListItem])
async def list_appointments_by_date(
    date: date_type,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AppointmentListItem]:
    """Lista turnos por fecha para la agenda del día."""
    from modules.appointments.repository import AppointmentRepository

    repo = AppointmentRepository(db)
    rows = await repo.get_by_date(date)
    return [
        AppointmentListItem(
            public_id=appointment.public_id,
            service_id=service.public_id,
            service_name=service.name,
            staff_id=staff.public_id,
            client_name=client.full_name or client.email,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            status=AppointmentStatus(appointment.status),
            notes=appointment.notes,
            intake_answers=appointment.intake_answers or {},
        )
        for appointment, service, staff, client in rows
    ]


# ---------------------------------------------------------------------------
# Disponibilidad
# ---------------------------------------------------------------------------


@router.get("/availability")
async def get_availability(
    service_id: PublicIdQuery,
    date: date_type,
    user: User | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> list[object]:
    """Consulta slots disponibles para un servicio en una fecha."""
    svc = AvailabilityService(db, redis)
    if user is None:
        set_tenant_context(None, is_admin=True)
        try:
            await _apply_tenant_context(db)
            repo = PublicRepository(db)
            service = await repo.get_service_by_public_id(service_id)
            if not service:
                return []
            return list(
                await svc.get_available_slots(service.store_id, service_id, date)
            )
        finally:
            set_tenant_context(None, False)

    return list(await svc.get_available_slots(user.store_id, service_id, date))


# ---------------------------------------------------------------------------
# Reservar turno
# ---------------------------------------------------------------------------


@router.post(
    "/", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED
)
async def book_appointment(
    data: AppointmentCreate,
    user: User = Depends(get_current_user),
    svc: AppointmentService = Depends(get_appointment_service),
    redis: Redis = Depends(get_redis),
) -> AppointmentResponse:
    """
    Reserva un turno con:
    - Idempotencia (X-Idempotency-Key).
    - Control de concurrencia pesimista.
    - Verificación de bloqueos de agenda.
    - Auditoría automática.
    - Notificación de confirmación por email.
    """
    # Idempotencia
    cached_res = await idempotency_guard(data.idempotency_key, redis)
    if cached_res:
        return AppointmentResponse.model_validate(cached_res)

    try:
        appointment, service, staff = await svc.book(
            data=cast(AppointmentBookPayload, data.model_dump()),
            store_id=user.store_id,
            actor=user,
        )
    except Exception:
        await idempotency_release(data.idempotency_key, redis)
        raise

    payload = AppointmentResponse(
        public_id=appointment.public_id,
        service_id=service.public_id,
        staff_id=staff.public_id,
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        status=AppointmentStatus(appointment.status),
        notes=appointment.notes,
        notes_staff=appointment.notes_staff,
        intake_answers=appointment.intake_answers or {},
    )
    await idempotency_save(data.idempotency_key, payload.model_dump(mode="json"), redis)
    return payload


# ---------------------------------------------------------------------------
# Cambios de estado (solo ADMIN / STAFF)
# ---------------------------------------------------------------------------


@router.patch("/{public_id}/cancel", response_model=AppointmentResponse)
async def cancel_appointment(
    public_id: PublicIdPath,
    user: User = Depends(get_current_user),
    svc: AppointmentService = Depends(get_appointment_service),
) -> AppointmentResponse:
    """Cancela un turno. Disponible para el cliente dueño, staff y admin."""
    appointment = await svc.cancel(public_id=public_id, actor=user)
    return _to_appointment_response(appointment)


@router.patch("/{public_id}/release", response_model=AppointmentResponse)
async def release_pending_appointment(
    public_id: PublicIdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> AppointmentResponse:
    """Libera un turno pendiente. Solo el dueÃ±o/administrador de la tienda."""
    require_roles(
        user,
        STORE_MANAGERS,
        "Solo el dueÃ±o o administrador de la tienda puede liberar un turno",
    )
    result = await db.execute(
        select(Appointment)
        .options(
            joinedload(Appointment.service),
            joinedload(Appointment.staff),
            joinedload(Appointment.client),
        )
        .where(
            Appointment.id == public_id,
            Appointment.store_id == user.store_id,
        )
        .with_for_update()
    )
    appointment = result.scalar_one_or_none()
    if not appointment:
        raise AppointmentNotFoundException(public_id)
    if appointment.status not in {
        AppointmentStatus.PENDING.value,
        AppointmentStatus.PENDING_PAYMENT.value,
    }:
        raise AppException(
            message="Solo se pueden liberar turnos pendientes",
            http_status=status.HTTP_409_CONFLICT,
            error_code="APPOINTMENT_NOT_RELEASABLE",
        )

    payment_result = await db.execute(
        select(Payment)
        .where(
            Payment.appointment_id == appointment.id,
            Payment.store_id == user.store_id,
        )
        .with_for_update()
    )
    payment = payment_result.scalar_one_or_none()
    if payment and payment.status in {
        PaymentStatus.APPROVED.value,
        PaymentStatus.MANUAL_CONFIRMED.value,
        PaymentStatus.REFUNDED.value,
    }:
        raise AppException(
            message="No se puede liberar un turno que ya tiene un pago acreditado",
            http_status=status.HTTP_409_CONFLICT,
            error_code="PAID_APPOINTMENT_NOT_RELEASABLE",
        )
    if payment and payment.status == PaymentStatus.PENDING.value:
        if payment.preference_id:
            try:
                await expire_mercadopago_preference(
                    db,
                    store_id=user.store_id,
                    preference_id=payment.preference_id,
                )
            except (RuntimeError, CircuitBreakerOpenError) as exc:
                raise AppException(
                    message=(
                        "No se liberÃ³ el turno porque Mercado Pago no pudo "
                        "vencer el enlace de pago"
                    ),
                    http_status=status.HTTP_502_BAD_GATEWAY,
                    error_code="PAYMENT_PREFERENCE_EXPIRATION_FAILED",
                ) from exc
        stamp_payment_from_status(
            payment,
            PaymentStatus.EXPIRED.value,
            payload={
                "reason": "manual_store_release",
                "released_by": user.public_id,
            },
        )

    previous_status = appointment.status
    appointment.apply_status_transition(AppointmentStatus.EXPIRED)
    await AuditRepository(db).log(
        action=AuditAction.STATUS_CHANGE,
        resource_type="Appointment",
        resource_id=appointment.public_id,
        actor=user,
        payload_before={"status": previous_status},
        payload_after={
            "status": appointment.status,
            "reason": "manual_store_release",
        },
    )
    db.add(
        OutboxMessage(
            store_id=user.store_id,
            event_type="appointment.released",
            payload={
                "appointment_id": appointment.id,
                "payment_id": payment.id if payment else None,
                "released_by": user.public_id,
            },
        )
    )
    await db.commit()

    cache_prefix = (
        f"availability:{appointment.store_id}:"
        f"{appointment.service.public_id}:{appointment.starts_at.date().isoformat()}"
    )
    for cache_key in (
        cache_prefix,
        f"{cache_prefix}:0:0",
        f"{cache_prefix}:0:1",
        f"{cache_prefix}:1:0",
        f"{cache_prefix}:1:1",
    ):
        await redis.delete(cache_key)
    return _to_appointment_response(appointment)


@router.patch("/{public_id}/confirm", response_model=AppointmentResponse)
async def confirm_appointment(
    public_id: PublicIdPath,
    user: User = Depends(get_current_user),
    svc: AppointmentService = Depends(get_appointment_service),
) -> AppointmentResponse:
    """Confirma un turno. Solo ADMIN o STAFF."""
    if user.role not in (UserRole.ADMIN, UserRole.STAFF):
        from core.exceptions import PermissionDeniedException

        raise PermissionDeniedException("confirmar turnos")

    appointment = await svc.confirm(public_id=public_id, actor=user)
    return _to_appointment_response(appointment)


@router.patch("/{public_id}/complete", response_model=AppointmentResponse)
async def complete_appointment(
    public_id: PublicIdPath,
    user: User = Depends(get_current_user),
    svc: AppointmentService = Depends(get_appointment_service),
) -> AppointmentResponse:
    """Marca un turno como completado. Solo ADMIN o STAFF."""
    if user.role not in (UserRole.ADMIN, UserRole.STAFF):
        from core.exceptions import PermissionDeniedException

        raise PermissionDeniedException("completar turnos")

    appointment = await svc.complete(public_id=public_id, actor=user)
    return _to_appointment_response(appointment)


@router.patch("/{public_id}/absent", response_model=AppointmentResponse)
async def mark_absent(
    public_id: PublicIdPath,
    user: User = Depends(get_current_user),
    svc: AppointmentService = Depends(get_appointment_service),
) -> AppointmentResponse:
    """Registra que el cliente no se presentó (AUSENTE). Solo ADMIN o STAFF."""
    if user.role not in (UserRole.ADMIN, UserRole.STAFF):
        from core.exceptions import PermissionDeniedException

        raise PermissionDeniedException("marcar ausencia")

    appointment = await svc.mark_absent(public_id=public_id, actor=user)
    return _to_appointment_response(appointment)


@router.patch("/{public_id}/reschedule", response_model=AppointmentResponse)
async def reschedule_appointment(
    public_id: PublicIdPath,
    data: AppointmentReschedule,
    user: User = Depends(get_current_user),
    svc: AppointmentService = Depends(get_appointment_service),
    redis: Redis = Depends(get_redis),
) -> AppointmentResponse:
    """
    Reprograma un turno a una nueva fecha/hora.
    - Cancela el original de forma atómica (con timestamp cancelled_at).
    - Crea uno nuevo con los mismos servicio/staff/cliente.
    - Ambas operaciones quedan registradas en audit_logs.
    """
    cached = await idempotency_guard(data.idempotency_key, redis)
    if cached:
        return AppointmentResponse.model_validate(cached)

    try:
        new_appointment, service, staff = await svc.reschedule(
            public_id=public_id,
            new_starts_at=data.new_starts_at,
            idempotency_key=data.idempotency_key,
            actor=user,
        )
    except Exception:
        await idempotency_release(data.idempotency_key, redis)
        raise
    payload = AppointmentResponse(
        public_id=new_appointment.public_id,
        service_id=service.public_id,
        staff_id=staff.public_id,
        starts_at=new_appointment.starts_at,
        ends_at=new_appointment.ends_at,
        status=AppointmentStatus(new_appointment.status),
        notes=new_appointment.notes,
        notes_staff=new_appointment.notes_staff,
        intake_answers=new_appointment.intake_answers or {},
    )
    await idempotency_save(data.idempotency_key, payload.model_dump(mode="json"), redis)
    return payload


@router.patch("/{public_id}/notes-staff", response_model=AppointmentResponse)
async def update_staff_notes(
    public_id: PublicIdPath,
    data: AppointmentNotesStaffUpdate,
    user: User = Depends(get_current_user),
    svc: AppointmentService = Depends(get_appointment_service),
) -> AppointmentResponse:
    """Agrega o edita las notas del profesional sobre el turno. Solo STAFF o ADMIN."""
    if user.role not in (UserRole.ADMIN, UserRole.STAFF):
        from core.exceptions import PermissionDeniedException

        raise PermissionDeniedException("editar notas del profesional")

    appointment = await svc.update_staff_notes(
        public_id=public_id, notes_staff=data.notes_staff, actor=user
    )
    return _to_appointment_response(appointment)


# ---------------------------------------------------------------------------
# Búsqueda avanzada con filtros dinámicos
# ---------------------------------------------------------------------------


@router.get("/search", response_model=AppointmentSearchResponse)
async def search_appointments(
    client_name: Optional[str] = Query(
        default=None, max_length=100, description="Nombre, apellido o email del cliente"
    ),
    staff_id: Optional[str] = Query(
        default=None,
        max_length=64,
        pattern=PUBLIC_ID_PATTERN,
        description="public_id del profesional",
    ),
    service_id: Optional[str] = Query(
        default=None,
        max_length=64,
        pattern=PUBLIC_ID_PATTERN,
        description="public_id del servicio",
    ),
    statuses: Optional[List[str]] = Query(
        default=None,
        max_length=10,
        description="Estados: pending, confirmed, cancelled, completed",
    ),
    from_date: Optional[date_type] = Query(
        default=None, description="Desde (YYYY-MM-DD)"
    ),
    to_date: Optional[date_type] = Query(
        default=None, description="Hasta (YYYY-MM-DD)"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AppointmentSearchResponse:
    """
    Búsqueda avanzada de turnos con filtros dinámicos y paginación.
    Todos los parámetros son opcionales y combinables.
    """
    from modules.appointments.repository import AppointmentRepository

    filters = AppointmentFilterParams(
        client_name=client_name,
        staff_id=staff_id,
        service_id=service_id,
        statuses=statuses,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )

    repo = AppointmentRepository(db)
    total, rows = await repo.search_appointments(filters, user.store_id)

    results = [
        AppointmentSearchResult(
            public_id=appointment.public_id,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            status=AppointmentStatus(appointment.status),
            notes=appointment.notes,
            notes_staff=appointment.notes_staff,
            intake_answers=appointment.intake_answers or {},
            service_name=service.name,
            service_id=service.public_id,
            staff_name=staff.display_name,
            staff_id=staff.public_id,
            client_name=client.full_name or client.email,
            client_id=client.public_id,
        )
        for appointment, service, staff, client in rows
    ]

    return AppointmentSearchResponse(
        total=total,
        page=filters.page,
        page_size=filters.page_size,
        results=results,
    )
