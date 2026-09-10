"""Lista de espera para el panel del dueno."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Path, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.availability_cache import AvailabilityCacheClient
from core.database import get_db
from core.redis import get_redis
from core.roles import STORE_MANAGERS, has_any_role, require_roles
from core.router import CanonicalAPIRouter
from core.validation import PUBLIC_ID_PATTERN
from modules.appointments.model import AppointmentStatus
from modules.appointments.schemas import AppointmentResponse
from modules.auth.dependencies import get_current_staff
from modules.stores.model import Store
from modules.users.model import User
from modules.waitlist.schemas import WaitlistBookRequest, WaitlistEntryResponse
from modules.waitlist.service import WaitlistService, to_row_dict

router = CanonicalAPIRouter(prefix="/waitlist", tags=["Waitlist"])
EntryIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


@router.get("/", response_model=list[WaitlistEntryResponse])
async def list_waitlist(
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> list[WaitlistEntryResponse]:
    """Entradas abiertas de la tienda. El contacto solo lo ve un administrador."""
    rows = await WaitlistService(db).list_open(user.store_id)
    show_contact = has_any_role(user, STORE_MANAGERS)
    return [
        WaitlistEntryResponse(**to_row_dict(row, show_contact=show_contact))
        for row in rows
    ]


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_waitlist_entry(
    entry_id: EntryIdPath,
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> None:
    require_roles(user, STORE_MANAGERS, "Solo un administrador puede dar de baja")
    svc = WaitlistService(db)
    entry = await svc.get_open(user.store_id, entry_id)
    await svc.cancel(entry)


@router.post(
    "/{entry_id}/book",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def book_from_waitlist(
    entry_id: EntryIdPath,
    data: WaitlistBookRequest,
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> AppointmentResponse:
    """El dueno reserva el turno para alguien de la lista (queda confirmado)."""
    require_roles(user, STORE_MANAGERS, "Solo un administrador puede reservar")
    svc = WaitlistService(db)
    entry = await svc.get_open(user.store_id, entry_id)
    store = await db.get(Store, user.store_id)
    if store is None:
        raise RuntimeError("tienda del usuario no encontrada")
    appointment, service, staff = await svc.book_from_panel(
        store=store,
        entry=entry,
        starts_at=data.starts_at,
        staff_public_id=data.staff_id,
        cache=cast(AvailabilityCacheClient, redis),
    )
    return AppointmentResponse(
        public_id=appointment.public_id,
        service_id=service.public_id,
        staff_id=staff.public_id,
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        status=AppointmentStatus(appointment.status),
        notes=appointment.notes,
        notes_staff=appointment.notes_staff,
        intake_answers=appointment.intake_answers or {},
        cancelled_at=appointment.cancelled_at,
        completed_at=appointment.completed_at,
    )
