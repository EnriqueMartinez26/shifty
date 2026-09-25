"""
Router de Turnos.

Responsabilidad única: recibir requests HTTP, delegar al AppointmentService
y serializar la respuesta. Sin lógica de negocio.
"""

from datetime import date as date_type, datetime
from typing import Annotated, AsyncGenerator, List, Optional, cast

from fastapi import Depends, Path, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.availability_cache import AvailabilityCacheClient
from core.router import CanonicalAPIRouter
from core.database import get_db, tenant_bypass
from core.exceptions import PermissionDeniedException, ValidationException
from core.idempotency import idempotency_guard, idempotency_release, idempotency_save
from core.keyset import (
    CURSOR_MAX_LENGTH,
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
)
from core.redis import get_availability_cache, get_redis
from core.roles import (
    ROLE_PROFESSIONAL,
    STORE_MANAGERS,
    canonical_role,
    has_any_role,
    require_roles,
)
from core.validation import PUBLIC_ID_PATTERN
from modules.appointments.availability import AvailabilityService
from modules.appointments.model import Appointment, AppointmentStatus
from modules.appointments.repository import AppointmentSearchRow
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
from modules.auth.dependencies import (
    get_current_staff,
    get_current_user,
    get_optional_current_user,
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
    availability_cache: Redis = Depends(get_availability_cache),
) -> AppointmentService:
    return AppointmentService(
        uow=uow, cache=cast(AvailabilityCacheClient, availability_cache)
    )


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
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> list[AppointmentListItem]:
    """Lista turnos por fecha para la agenda del día."""
    from modules.appointments.repository import AppointmentRepository

    repo = AppointmentRepository(db)
    rows = await repo.get_by_date(date, user.store_id)
    # El telefono del cliente solo lo ve un administrador (dato personal).
    show_phone = has_any_role(user, STORE_MANAGERS)
    return [
        AppointmentListItem(
            public_id=appointment.public_id,
            service_id=service.public_id,
            service_name=service.name,
            staff_id=staff.public_id,
            staff_name=staff.display_name,
            client_name=client.full_name or client.email,
            client_phone=client.phone if show_phone else None,
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
    availability_cache: Redis = Depends(get_availability_cache),
) -> list[object]:
    """Consulta slots disponibles para un servicio en una fecha.

    Sin token la respuesta es la del portal: un bloqueo sale como "No
    disponible" y nunca con el motivo que tipeo el duenio (AUD2-B1-04).
    """
    svc = AvailabilityService(db, availability_cache)
    if user is None:
        async with tenant_bypass(db):
            repo = PublicRepository(db)
            service = await repo.get_service_by_public_id(service_id)
            if not service:
                return []
            # El motivo de un bloqueo es un dato personal del profesional y
            # esta ruta es anonima (el service_id sale de /public/services):
            # regla 20, mismo criterio que public_api/router.py.
            return list(
                await svc.get_available_slots(
                    service.store_id, service_id, date, hide_private_reasons=True
                )
            )

    return list(await svc.get_available_slots(user.store_id, service_id, date))


# ---------------------------------------------------------------------------
# Reservar turno
# ---------------------------------------------------------------------------


@router.post(
    "/", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED
)
async def book_appointment(
    data: AppointmentCreate,
    user: User = Depends(get_current_staff),
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

    Con ``client_name`` + ``client_phone`` el turno es para ese cliente
    (FF-04): ver ``_book_for_client``.
    """
    if data.for_client:
        return await _book_for_client(data, user, svc, redis)

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


def _panel_booking_staff(user: User, data: AppointmentCreate) -> str | None:
    """Quien puede cargar que turno para un cliente (FF-04). 403 si no.

    - Admin y recepcion: cualquier profesional de la tienda, o "cualquiera".
    - Profesional: solo en su propia agenda (``Staff.id == User.id``, como
      acota reportes); sin ``staff_id`` se asume el suyo.
    - ``allow_outside_schedule``: solo el admin (``STORE_MANAGERS``).
    """
    if data.allow_outside_schedule:
        require_roles(
            user,
            STORE_MANAGERS,
            "Solo el dueno o administrador puede cargar un turno fuera de horario",
        )
    if canonical_role(user) != ROLE_PROFESSIONAL:
        return data.staff_id
    if data.staff_id not in (None, user.id):
        raise PermissionDeniedException("reservar en la agenda de otro profesional")
    return str(user.id)


async def _book_for_client(
    data: AppointmentCreate,
    user: User,
    svc: AppointmentService,
    redis: Redis,
) -> AppointmentResponse:
    """Alta del panel para un cliente (FF-04). La clave de idempotencia va
    namespaceada por tienda (patron de AUD2-B1-06): la misma cadena mandada
    desde otra tienda no devuelve este turno."""
    staff_id = _panel_booking_staff(user, data)
    cache_key = f"panel-client:{user.store_id}:{data.idempotency_key}"
    cached = await idempotency_guard(cache_key, redis)
    if cached:
        return AppointmentResponse.model_validate(cached)
    try:
        appointment, service, staff = await svc.book_for_client(
            data={
                "service_id": data.service_id,
                "staff_id": staff_id,
                "starts_at": data.starts_at,
                "notes": data.notes,
                "idempotency_key": data.idempotency_key,
                "client_name": str(data.client_name),
                "client_phone": str(data.client_phone),
                "client_email": str(data.client_email) if data.client_email else None,
                "allow_outside_schedule": data.allow_outside_schedule,
            },
            store_id=user.store_id,
            actor=user,
        )
    except Exception:
        await idempotency_release(cache_key, redis)
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
    await idempotency_save(cache_key, payload.model_dump(mode="json"), redis)
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
    """Cancela un turno de la tienda. Lo usan el staff y el admin.

    El rol cliente no inicia sesión: cancela por
    ``/public/client/appointments/{id}/cancel``. No verifica titularidad:
    cualquier usuario autenticado de la tienda puede cancelar cualquier turno
    de esa tienda.
    """
    appointment = await svc.cancel(public_id=public_id, actor=user)
    return _to_appointment_response(appointment)


@router.patch("/{public_id}/release", response_model=AppointmentResponse)
async def release_pending_appointment(
    public_id: PublicIdPath,
    user: User = Depends(get_current_user),
    svc: AppointmentService = Depends(get_appointment_service),
) -> AppointmentResponse:
    """Libera un turno pendiente. Solo el dueno/administrador de la tienda."""
    require_roles(
        user,
        STORE_MANAGERS,
        "Solo el dueno o administrador de la tienda puede liberar un turno",
    )
    appointment = await svc.release_pending(public_id=public_id, actor=user)
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
    # ge Y le (regla 9): sin tope, (page - 1) * page_size desbordaba el entero
    # de la base en el OFFSET y salia 500 (B1-03).
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=20, ge=1, le=100),
    # F3-06 (aditivo): el total es el mismo en todas las paginas; el panel lo
    # pide en la primera y lo saltea en las demas (``total`` vuelve null).
    include_total: bool = Query(
        default=True, description="false: no cuenta el total (total = null)"
    ),
    # F3-08 (aditivo): `next_cursor` de la pagina anterior; reemplaza a `page`.
    after: Optional[str] = Query(default=None, max_length=CURSOR_MAX_LENGTH),
    user: User = Depends(get_current_staff),
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
    total, rows, has_more = await repo.search_appointments(
        filters,
        user.store_id,
        include_total=include_total,
        after=_search_key(after, page),
    )
    # El telefono del cliente solo lo ve un administrador (dato personal).
    show_phone = has_any_role(user, STORE_MANAGERS)
    results = [_to_search_result(row, show_phone=show_phone) for row in rows]

    return AppointmentSearchResponse(
        total=total,
        page=filters.page,
        page_size=filters.page_size,
        results=results,
        next_cursor=(
            encode_cursor(rows[-1][0].starts_at, rows[-1][0].id) if has_more else None
        ),
    )


def _search_key(after: Optional[str], page: int) -> Optional[tuple[datetime, str]]:
    """Clave ``(starts_at, id)`` del cursor ``after``; 422 si no es valido.

    ``after`` y ``page`` > 1 a la vez es ambiguo (dos formas de decir donde
    empieza la pagina) y tambien es 422.
    """
    if after is None:
        return None
    if page != 1:
        raise ValidationException("after y page no se combinan")
    try:
        return decode_cursor(after)
    except InvalidCursorError:
        raise ValidationException("Cursor de paginacion invalido") from None


def _to_search_result(
    row: AppointmentSearchRow, *, show_phone: bool
) -> AppointmentSearchResult:
    appointment, service, staff_id, staff_name, client = row
    return AppointmentSearchResult(
        public_id=appointment.public_id,
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        status=AppointmentStatus(appointment.status),
        notes=appointment.notes,
        notes_staff=appointment.notes_staff,
        intake_answers=appointment.intake_answers or {},
        cancelled_at=appointment.cancelled_at,
        completed_at=appointment.completed_at,
        service_name=service.name,
        service_id=service.public_id,
        staff_name=staff_name,
        staff_id=staff_id,
        client_name=client.full_name or client.email,
        client_id=client.public_id,
        client_phone=client.phone if show_phone else None,
    )
