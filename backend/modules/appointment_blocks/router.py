from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.validation import PUBLIC_ID_PATTERN
from modules.appointment_blocks.schemas import (
    AppointmentBlockBatchResponse,
    AppointmentBlockCreate,
    AppointmentBlockResponse,
    AppointmentBlockUpdate,
    BlockTemplateResponse,
    RecurringAppointmentBlockCreate,
)
from modules.auth.dependencies import get_current_user
from modules.staff.model import Staff, StaffBlock
from modules.users.model import User, UserRole

router = APIRouter(prefix="/appointment-blocks", tags=["Appointment Blocks"])
PublicIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)]


def _can_manage_blocks(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.STAFF) or user.is_global_admin


def _to_response(block: StaffBlock) -> AppointmentBlockResponse:
    return AppointmentBlockResponse(
        public_id=block.id,
        staff_id=block.staff_id,
        starts_at=block.starts_at,
        ends_at=block.ends_at,
        reason=block.reason,
        is_active=block.is_active,
    )


def _recurrence_step(recurrence: str) -> timedelta:
    if recurrence == "daily":
        return timedelta(days=1)
    if recurrence == "weekly":
        return timedelta(days=7)
    return timedelta(0)


@router.get("/", response_model=list[AppointmentBlockResponse])
async def list_blocks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage_blocks(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenés permiso para ver bloqueos")
    result = await db.execute(
        select(StaffBlock)
        .where(StaffBlock.store_id == user.store_id)
        .order_by(StaffBlock.start_time.asc())
    )
    return [_to_response(block) for block in result.scalars().all()]


@router.post("/", response_model=AppointmentBlockResponse, status_code=status.HTTP_201_CREATED)
async def create_block(
    data: AppointmentBlockCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage_blocks(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenés permiso para crear bloqueos")
    staff_result = await db.execute(
        select(Staff).where(Staff.id == data.staff_id, Staff.store_id == user.store_id, Staff.is_active.is_(True))
    )
    staff = staff_result.scalar_one_or_none()
    if not staff:
        raise HTTPException(status_code=404, detail="Profesional no encontrado")
    block = StaffBlock(
        store_id=user.store_id,
        staff_id=staff.id,
        start_time=data.starts_at,
        end_time=data.ends_at,
        reason=data.reason,
    )
    db.add(block)
    await db.commit()
    await db.refresh(block)
    return _to_response(block)


@router.post("/batch", response_model=AppointmentBlockBatchResponse, status_code=status.HTTP_201_CREATED)
async def create_block_batch(
    data: RecurringAppointmentBlockCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage_blocks(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenés permiso para crear bloqueos")

    staff_result = await db.execute(
        select(Staff).where(Staff.id == data.staff_id, Staff.store_id == user.store_id, Staff.is_active.is_(True))
    )
    staff = staff_result.scalar_one_or_none()
    if not staff:
        raise HTTPException(status_code=404, detail="Profesional no encontrado")

    ranges: list[tuple] = [(data.starts_at, data.ends_at)]
    if data.recurrence != "none":
        current_start = data.starts_at
        current_end = data.ends_at
        step = _recurrence_step(data.recurrence)
        while len(ranges) < data.max_occurrences:
            current_start = current_start + step
            current_end = current_end + step
            if data.recurrence_until and current_start > data.recurrence_until:
                break
            ranges.append((current_start, current_end))

    created_blocks: list[StaffBlock] = []
    for starts_at, ends_at in ranges:
        block = StaffBlock(
            store_id=user.store_id,
            staff_id=staff.id,
            start_time=starts_at,
            end_time=ends_at,
            reason=data.reason,
        )
        db.add(block)
        created_blocks.append(block)

    await db.commit()
    for block in created_blocks:
        await db.refresh(block)

    responses = [_to_response(block) for block in created_blocks]
    return AppointmentBlockBatchResponse(created=len(responses), blocks=responses)


@router.get("/templates", response_model=list[BlockTemplateResponse])
async def list_block_templates(user: User = Depends(get_current_user)):
    if not _can_manage_blocks(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenés permiso para ver plantillas")
    return [
        BlockTemplateResponse(key="vacaciones", label="Vacaciones", reason="Vacaciones"),
        BlockTemplateResponse(key="no_atender", label="No atender", reason="No atender"),
        BlockTemplateResponse(key="capacitacion", label="Capacitación", reason="Capacitación"),
        BlockTemplateResponse(key="personal", label="Motivo personal", reason="Motivo personal"),
    ]


@router.patch("/{public_id}", response_model=AppointmentBlockResponse)
async def update_block(
    public_id: PublicIdPath,
    data: AppointmentBlockUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage_blocks(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenés permiso para editar bloqueos")
    result = await db.execute(
        select(StaffBlock).where(StaffBlock.id == public_id, StaffBlock.store_id == user.store_id)
    )
    block = result.scalar_one_or_none()
    if not block:
        raise HTTPException(status_code=404, detail="Bloqueo no encontrado")
    update_data = data.model_dump(exclude_unset=True)
    if "starts_at" in update_data:
        block.start_time = update_data["starts_at"]
    if "ends_at" in update_data:
        block.end_time = update_data["ends_at"]
    if block.start_time >= block.end_time:
        raise HTTPException(status_code=422, detail="El inicio debe ser anterior al fin")
    for key in ("reason", "is_active"):
        if key in update_data:
            setattr(block, key, update_data[key])
    await db.commit()
    await db.refresh(block)
    return _to_response(block)


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_block(
    public_id: PublicIdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage_blocks(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenés permiso para eliminar bloqueos")
    result = await db.execute(
        select(StaffBlock).where(StaffBlock.id == public_id, StaffBlock.store_id == user.store_id)
    )
    block = result.scalar_one_or_none()
    if not block:
        raise HTTPException(status_code=404, detail="Bloqueo no encontrado")
    block.is_active = False
    await db.commit()
