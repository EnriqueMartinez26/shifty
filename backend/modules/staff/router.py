from typing import Annotated

from fastapi import Depends, Path, Response, status
from core.router import CanonicalAPIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.exceptions import (
    AppException,
    ResourceNotFoundException,
    StaffNotFoundException,
    ValidationException,
)
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_admin, get_current_user
from modules.staff.mappers import to_schedule_response, to_staff_response
from modules.staff.repository import StaffRepository
from modules.staff.schemas import (
    ScheduleCreate,
    ScheduleUpdate,
    ScheduleResponse,
    StaffCreate,
    StaffResponse,
    StaffUpdate,
)
from modules.users.model import User

router = CanonicalAPIRouter(prefix="/staff", tags=["Staff"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


@router.post("/", response_model=StaffResponse, status_code=status.HTTP_201_CREATED)
async def create_staff(
    data: StaffCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> StaffResponse:
    repo = StaffRepository(db)
    try:
        created = await repo.create(
            data.model_dump(exclude={"service_ids"}), admin.store_id, data.service_ids
        )
        loaded = await repo.get_by_id(created.public_id, admin.store_id)
        if not loaded:
            raise AppException(
                message="No se pudo recargar el staff creado",
                http_status=500,
                error_code="STAFF_RELOAD_FAILED",
            )
        return to_staff_response(loaded)
    except ValueError as exc:
        raise ValidationException(str(exc))


@router.get("/", response_model=list[StaffResponse])
async def list_staff(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[StaffResponse]:
    repo = StaffRepository(db)
    members = await repo.get_all(user.store_id)
    return [to_staff_response(member) for member in members]


@router.get("/{public_id}", response_model=StaffResponse)
async def get_staff(
    public_id: PublicIdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StaffResponse:
    repo = StaffRepository(db)
    staff = await repo.get_by_id(public_id, user.store_id)
    if not staff:
        raise StaffNotFoundException(identifier=public_id)
    return to_staff_response(staff)


@router.post("/{public_id}/schedules", response_model=ScheduleResponse)
async def add_staff_schedule(
    public_id: PublicIdPath,
    data: ScheduleCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    repo = StaffRepository(db)
    staff = await repo.get_by_id(public_id, admin.store_id)
    if not staff:
        raise StaffNotFoundException(identifier=public_id)

    try:
        schedule = await repo.add_schedule(staff, data.model_dump(), admin.store_id)
    except ValueError as exc:
        raise ValidationException(str(exc))
    return to_schedule_response(schedule)


@router.patch("/{public_id}/schedules/{schedule_id}", response_model=ScheduleResponse)
async def update_staff_schedule(
    public_id: PublicIdPath,
    schedule_id: PublicIdPath,
    data: ScheduleUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    """Corrige una franja horaria mal cargada."""
    repo = StaffRepository(db)
    staff = await repo.get_by_id(public_id, admin.store_id)
    if not staff:
        raise StaffNotFoundException(identifier=public_id)

    schedule = await repo.get_schedule(staff, schedule_id)
    if not schedule:
        raise ResourceNotFoundException(resource="Horario", identifier=schedule_id)

    try:
        actualizado = await repo.update_schedule(
            staff, schedule, data.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise ValidationException(str(exc))
    return to_schedule_response(actualizado)


@router.delete(
    "/{public_id}/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_staff_schedule(
    public_id: PublicIdPath,
    schedule_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Elimina una franja horaria.

    Sin esto un horario mal cargado era permanente y seguia generando turnos
    reservables que la tienda no podia atender.
    """
    repo = StaffRepository(db)
    staff = await repo.get_by_id(public_id, admin.store_id)
    if not staff:
        raise StaffNotFoundException(identifier=public_id)

    schedule = await repo.get_schedule(staff, schedule_id)
    if not schedule:
        raise ResourceNotFoundException(resource="Horario", identifier=schedule_id)

    await repo.delete_schedule(schedule)


@router.patch("/{public_id}/services")
async def update_staff_services(
    public_id: PublicIdPath,
    service_ids: list[str],
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    repo = StaffRepository(db)
    staff = await repo.get_by_id(public_id, admin.store_id)
    if not staff:
        raise StaffNotFoundException(identifier=public_id)

    try:
        await repo.update_services(staff, service_ids)
    except ValueError as exc:
        raise ValidationException(str(exc))
    return {"message": "Servicios actualizados correctamente"}


@router.put("/{public_id}", response_model=StaffResponse)
@router.patch("/{public_id}", response_model=StaffResponse)
async def update_staff(
    public_id: PublicIdPath,
    data: StaffUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> StaffResponse:
    repo = StaffRepository(db)
    staff = await repo.get_by_id(public_id, admin.store_id)
    if not staff:
        raise StaffNotFoundException(identifier=public_id)

    try:
        updated = await repo.update_profile(
            staff,
            first_name=data.first_name,
            last_name=data.last_name,
            email=data.email,
            display_name=data.display_name,
            service_public_ids=data.service_ids,
            is_active=data.is_active,
        )
    except ValueError as exc:
        raise ValidationException(str(exc))

    loaded = await repo.get_by_id(updated.public_id, admin.store_id)
    if not loaded:
        raise AppException(
            message="No se pudo recargar el staff actualizado",
            http_status=500,
            error_code="STAFF_RELOAD_FAILED",
        )
    return to_staff_response(loaded)


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_staff(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    repo = StaffRepository(db)
    staff = await repo.get_by_id(public_id, admin.store_id)
    if not staff:
        raise StaffNotFoundException(identifier=public_id)
    await repo.soft_delete(staff)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
