"""
Router de Turnos.

Responsabilidad única: recibir requests HTTP, delegar al AppointmentService
y serializar la respuesta. Sin lógica de negocio.
"""

from datetime import date as date_type
from typing import Annotated, Optional, List

from fastapi import Depends, Path, Query, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.router import CanonicalAPIRouter
from core.database import _apply_tenant_context, get_db, set_tenant_context
from core.idempotency import idempotency_guard, idempotency_release, idempotency_save
from core.redis import get_redis
from core.validation import PUBLIC_ID_PATTERN
from core.vercel_queue import extract_vercel_oidc_token
from modules.appointments.availability import AvailabilityService
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
from modules.appointments.service import AppointmentService
from modules.auth.dependencies import get_current_user, get_optional_current_user

# AI AGENT NOTE: use public_api as the stable runtime import path for public booking data access.
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

from typing import AsyncGenerator


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
    return AppointmentService(uow=uow, redis=redis)


def _to_appointment_response(appointment) -> AppointmentResponse:
    service = getattr(appointment, "service", None)
    staff = getattr(appointment, "staff", None)
    return AppointmentResponse(
        public_id=appointment.public_id,
        service_id=service.public_id if service else str(appointment.service_id),
        staff_id=staff.public_id if staff else str(appointment.staff_id),
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        status=appointment.status,
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
):
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
            client_name=f"{client.first_name or ''} {client.last_name or ''}".strip()
            or client.email,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            status=appointment.status,
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
):
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
            return await svc.get_available_slots(service.store_id, service_id, date)
        finally:
            set_tenant_context(None, False)

    return await svc.get_available_slots(user.store_id, service_id, date)


# ---------------------------------------------------------------------------
# Reservar turno
# ---------------------------------------------------------------------------


@router.post("/", response_model=AppointmentResponse)
async def book_appointment(
    request: Request,
    data: AppointmentCreate,
    user: User = Depends(get_current_user),
    svc: AppointmentService = Depends(get_appointment_service),
    redis: Redis = Depends(get_redis),
):
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
        return cached_res

    try:
        appointment, service, staff = await svc.book(
            data=data.model_dump(),
            store_id=user.store_id,
            actor=user,
            vercel_oidc_token=extract_vercel_oidc_token(request),
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
        status=appointment.status,
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
):
    """Cancela un turno. Disponible para el cliente dueño, staff y admin."""
    appointment = await svc.cancel(public_id=public_id, actor=user)
    return _to_appointment_response(appointment)


@router.patch("/{public_id}/confirm", response_model=AppointmentResponse)
async def confirm_appointment(
    public_id: PublicIdPath,
    user: User = Depends(get_current_user),
    svc: AppointmentService = Depends(get_appointment_service),
):
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
):
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
):
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
):
    """
    Reprograma un turno a una nueva fecha/hora.
    - Cancela el original de forma atómica (con timestamp cancelled_at).
    - Crea uno nuevo con los mismos servicio/staff/cliente.
    - Ambas operaciones quedan registradas en audit_logs.
    """
    cached = await idempotency_guard(data.idempotency_key, redis)
    if cached:
        return cached

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
        status=new_appointment.status,
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
):
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
):
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
    total, rows = await repo.search_appointments(filters)

    results = [
        AppointmentSearchResult(
            public_id=appointment.public_id,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            status=appointment.status,
            notes=appointment.notes,
            notes_staff=appointment.notes_staff,
            intake_answers=appointment.intake_answers or {},
            service_name=service.name,
            service_id=service.public_id,
            staff_name=staff.display_name,
            staff_id=staff.public_id,
            client_name=(
                f"{client.first_name or ''} {client.last_name or ''}".strip()
                or client.email
            ),
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
