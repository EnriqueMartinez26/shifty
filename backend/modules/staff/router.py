from typing import Annotated

from fastapi import Depends, Path, status
from core.router import CanonicalAPIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from core.exceptions import (
    AppException,
    StaffNotFoundException,
    ValidationException,
)
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_admin, get_current_user
from modules.users.model import User
from modules.staff.schemas import (
    StaffCreate,
    StaffUpdate,
    StaffResponse,
    ScheduleCreate,
    ScheduleResponse,
)
from modules.staff.repository import StaffRepository

router = CanonicalAPIRouter(prefix="/staff", tags=["Staff"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


def _to_staff_response(member) -> StaffResponse:
    return StaffResponse(
        public_id=member.public_id,
        display_name=member.display_name,
        first_name=member.first_name or "",
        last_name=member.last_name or "",
        email=member.email,
        is_active=member.is_active,
        service_ids=member.service_ids or [],
        services=member.services,
        schedules=member.schedules,
    )


@router.post("/", response_model=StaffResponse, status_code=status.HTTP_201_CREATED)
async def create_staff(
    data: StaffCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = StaffRepository(db)
    try:
        created = await repo.create(
            data.model_dump(exclude={"service_ids"}), admin.store_id, data.service_ids
        )
        loaded = await repo.get_by_id(created.public_id)
        if not loaded:
            raise AppException(
                message="No se pudo recargar el staff creado",
                http_status=500,
                error_code="STAFF_RELOAD_FAILED",
            )
        return _to_staff_response(loaded)
    except ValueError as e:
        raise ValidationException(str(e))


@router.get("/", response_model=list[StaffResponse])
async def list_staff(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    repo = StaffRepository(db)
    members = await repo.get_all()
    return [_to_staff_response(member) for member in members]


@router.get("/{public_id}", response_model=StaffResponse)
async def get_staff(
    public_id: PublicIdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = StaffRepository(db)
    staff = await repo.get_by_id(public_id)
    if not staff:
        raise StaffNotFoundException(identifier=public_id)
    return _to_staff_response(staff)


@router.post("/{public_id}/schedules", response_model=ScheduleResponse)
async def add_staff_schedule(
    public_id: PublicIdPath,
    data: ScheduleCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = StaffRepository(db)
    staff = await repo.get_by_id(public_id)
    if not staff:
        raise StaffNotFoundException(identifier=public_id)

    return await repo.add_schedule(staff, data.model_dump(), admin.store_id)


@router.patch("/{public_id}/services")
async def update_staff_services(
    public_id: PublicIdPath,
    service_ids: list[str],
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = StaffRepository(db)
    staff = await repo.get_by_id(public_id)
    if not staff:
        raise StaffNotFoundException(identifier=public_id)

    await repo.update_services(staff, service_ids)
    return {"message": "Servicios actualizados correctamente"}


@router.put("/{public_id}", response_model=StaffResponse)
@router.patch("/{public_id}", response_model=StaffResponse)
async def update_staff(
    public_id: PublicIdPath,
    data: StaffUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Actualiza display_name, servicios y/o estado activo de un profesional."""
    repo = StaffRepository(db)
    staff = await repo.get_by_id(public_id)
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

    loaded = await repo.get_by_id(updated.public_id)
    return _to_staff_response(loaded)


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_staff(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = StaffRepository(db)
    staff = await repo.get_by_id(public_id)
    if not staff:
        raise StaffNotFoundException(identifier=public_id)
    await repo.soft_delete(staff)
