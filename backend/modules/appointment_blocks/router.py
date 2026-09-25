from collections.abc import AsyncGenerator
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, cast

from fastapi import Depends, Path, Query, status
from redis.asyncio import Redis
from core.router import CanonicalAPIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from core.availability_cache import AvailabilityCacheClient
from core.database import get_db
from core.redis import get_availability_cache
from core.exceptions import PermissionDeniedException, ValidationException
from core.roles import STORE_MANAGERS, has_any_role
from core.uow import AsyncSqlAlchemyUnitOfWork
from core.utils import ensure_utc_aware, local_day_start
from core.validation import PUBLIC_ID_PATTERN
from modules.appointment_blocks.schemas import (
    AffectedAppointmentResponse,
    AppointmentBlockBatchResponse,
    AppointmentBlockCreate,
    AppointmentBlockResponse,
    AppointmentBlockUpdate,
    BlockPreviewRequest,
    BlockPreviewResponse,
    BlockTemplateResponse,
    RecurringAppointmentBlockCreate,
    StoreWideBlockCreate,
    StoreWideBlockResponse,
)
from modules.appointment_blocks.service import (
    AffectedAppointment,
    AppointmentBlockService,
    expand_ranges,
)
from modules.appointments.repository import AppointmentRepository
from modules.auth.dependencies import get_current_user
from modules.staff.model import StaffBlock
from modules.users.model import User, UserRole

router = CanonicalAPIRouter(prefix="/appointment-blocks", tags=["Appointment Blocks"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


def _can_manage_blocks(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.STAFF) or user.is_global_admin


def _require_manage(user: User, action: str) -> None:
    if not _can_manage_blocks(user):
        raise PermissionDeniedException(action=f"No tenés permiso para {action}")


async def get_block_service(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    availability_cache: Redis = Depends(get_availability_cache),
) -> AsyncGenerator[AppointmentBlockService, None]:
    uow = AsyncSqlAlchemyUnitOfWork(db)
    async with uow:
        yield AppointmentBlockService(
            uow=uow, cache=cast(AvailabilityCacheClient, availability_cache), actor=user
        )


def _to_response(block: StaffBlock) -> AppointmentBlockResponse:
    # Siempre UTC con zona: desde que el alta no hace refresh por bloqueo
    # (B1-14) el objeto conserva el offset que mando el cliente, y SQLite
    # devuelve naive. La base guarda UTC; la respuesta tambien.
    return AppointmentBlockResponse(
        public_id=block.id,
        staff_id=block.staff_id,
        starts_at=ensure_utc_aware(block.starts_at).astimezone(timezone.utc),
        ends_at=ensure_utc_aware(block.ends_at).astimezone(timezone.utc),
        reason=block.reason,
        is_active=block.is_active,
    )


def _to_affected(item: AffectedAppointment, user: User) -> AffectedAppointmentResponse:
    appointment = item.appointment
    # El telefono del cliente solo lo ve un administrador (dato personal).
    phone = appointment.client_phone if has_any_role(user, STORE_MANAGERS) else None
    return AffectedAppointmentResponse(
        public_id=appointment.public_id,
        client_name=appointment.client_name or "",
        client_phone=phone,
        service_name=getattr(appointment.service, "name", ""),
        staff_name=getattr(appointment.staff, "display_name", ""),
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        status=appointment.status,
        blocker=item.reason,
        cancellable=item.cancellable,
    )


# F4-07: el rango de la agenda, en dias locales, tiene tope (regla 9).
MAX_BLOCK_LIST_DAYS = 400


def _block_window(
    from_date: date | None, to_date: date | None
) -> tuple[datetime, datetime] | None:
    """``[inicio del primer dia, inicio del dia siguiente al ultimo)`` en UTC.

    Dias LOCALES cortados con ``local_day_start`` (regla 24). Los dos o
    ninguno; ``None`` es "sin rango" (la respuesta de siempre).
    """
    if from_date is None and to_date is None:
        return None
    if from_date is None or to_date is None:
        raise ValidationException("from_date y to_date van juntos")
    if to_date < from_date:
        raise ValidationException("to_date no puede ser anterior a from_date")
    if (to_date - from_date).days > MAX_BLOCK_LIST_DAYS:
        raise ValidationException(
            f"El rango no puede superar {MAX_BLOCK_LIST_DAYS} dias"
        )
    return local_day_start(from_date), local_day_start(to_date + timedelta(days=1))


@router.get("/", response_model=list[AppointmentBlockResponse])
async def list_blocks(
    # F4-07 (aditivo): sin ninguno de los tres, todos los bloqueos de la
    # tienda, activos e inactivos, como siempre. ``include_inactive`` ausente
    # conserva ese default; ``false`` saca los desactivados.
    from_date: date | None = Query(default=None, description="Dia local (YYYY-MM-DD)"),
    to_date: date | None = Query(default=None, description="Dia local (YYYY-MM-DD)"),
    include_inactive: bool | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AppointmentBlockResponse]:
    if not _can_manage_blocks(user):
        raise PermissionDeniedException(action="No tenés permiso para ver bloqueos")
    blocks = await AppointmentRepository(db).list_store_blocks(
        str(user.store_id),
        window=_block_window(from_date, to_date),
        include_inactive=include_inactive is not False,
    )
    return [_to_response(block) for block in blocks]


@router.post(
    "/preview", response_model=BlockPreviewResponse, status_code=status.HTTP_200_OK
)
async def preview_block(
    data: BlockPreviewRequest,
    user: User = Depends(get_current_user),
    service: AppointmentBlockService = Depends(get_block_service),
) -> BlockPreviewResponse:
    """Turnos que caerian dentro del bloqueo, sin escribir nada."""
    _require_manage(user, "ver bloqueos")
    ranges = expand_ranges(
        data.starts_at,
        data.ends_at,
        data.recurrence,
        data.recurrence_until,
        data.max_occurrences,
    )
    affected = await service.preview(staff_id=data.staff_id, ranges=ranges)
    return BlockPreviewResponse(
        ranges=len(ranges), affected=[_to_affected(a, user) for a in affected]
    )


@router.post(
    "/store-wide",
    response_model=StoreWideBlockResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_store_wide_block(
    data: StoreWideBlockCreate,
    user: User = Depends(get_current_user),
    service: AppointmentBlockService = Depends(get_block_service),
) -> StoreWideBlockResponse:
    """Cierra la tienda entera en un rango: bloquea a todo el personal activo."""
    _require_manage(user, "crear bloqueos")
    result = await service.create_blocks(
        staff_id=None,
        ranges=[(data.starts_at, data.ends_at)],
        reason=data.reason,
        cancel_affected=data.cancel_affected,
    )
    return StoreWideBlockResponse(
        blocked_staff=len(result.blocks),
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        reason=data.reason,
    )


@router.post(
    "/", response_model=AppointmentBlockResponse, status_code=status.HTTP_201_CREATED
)
async def create_block(
    data: AppointmentBlockCreate,
    user: User = Depends(get_current_user),
    service: AppointmentBlockService = Depends(get_block_service),
) -> AppointmentBlockResponse:
    _require_manage(user, "crear bloqueos")
    result = await service.create_blocks(
        staff_id=data.staff_id,
        ranges=[(data.starts_at, data.ends_at)],
        reason=data.reason,
        cancel_affected=data.cancel_affected,
    )
    return _to_response(result.blocks[0])


@router.post(
    "/batch",
    response_model=AppointmentBlockBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_block_batch(
    data: RecurringAppointmentBlockCreate,
    user: User = Depends(get_current_user),
    service: AppointmentBlockService = Depends(get_block_service),
) -> AppointmentBlockBatchResponse:
    _require_manage(user, "crear bloqueos")
    ranges = expand_ranges(
        data.starts_at,
        data.ends_at,
        data.recurrence,
        data.recurrence_until,
        data.max_occurrences,
    )
    result = await service.create_blocks(
        staff_id=data.staff_id,
        ranges=ranges,
        reason=data.reason,
        cancel_affected=data.cancel_affected,
    )
    responses = [_to_response(block) for block in result.blocks]
    return AppointmentBlockBatchResponse(created=len(responses), blocks=responses)


@router.get("/templates", response_model=list[BlockTemplateResponse])
async def list_block_templates(
    user: User = Depends(get_current_user),
) -> list[BlockTemplateResponse]:
    if not _can_manage_blocks(user):
        raise PermissionDeniedException(action="No tenés permiso para ver plantillas")
    return [
        BlockTemplateResponse(
            key="vacaciones", label="Vacaciones", reason="Vacaciones"
        ),
        BlockTemplateResponse(
            key="no_atender", label="No atender", reason="No atender"
        ),
        BlockTemplateResponse(
            key="capacitacion", label="Capacitación", reason="Capacitación"
        ),
        BlockTemplateResponse(
            key="personal", label="Motivo personal", reason="Motivo personal"
        ),
    ]


@router.patch("/{public_id}", response_model=AppointmentBlockResponse)
async def update_block(
    public_id: PublicIdPath,
    data: AppointmentBlockUpdate,
    user: User = Depends(get_current_user),
    service: AppointmentBlockService = Depends(get_block_service),
) -> AppointmentBlockResponse:
    _require_manage(user, "editar bloqueos")
    changes = data.model_dump(exclude_unset=True)
    cancel_affected = bool(changes.pop("cancel_affected", False))
    block = await service.update_block(
        public_id, changes, cancel_affected=cancel_affected
    )
    return _to_response(block)


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_block(
    public_id: PublicIdPath,
    user: User = Depends(get_current_user),
    service: AppointmentBlockService = Depends(get_block_service),
) -> None:
    _require_manage(user, "eliminar bloqueos")
    await service.delete_block(public_id)
