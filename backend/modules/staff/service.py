"""Alta, edicion y baja de personal, horarios y servicios: dueno de la transaccion.

El repositorio commiteaba por su cuenta (deuda declarada). Al agregar
``kind`` (persona o recurso) se movieron los commits de alta/edicion/baja aca,
como en el modulo de referencia ``appointments``; el 2026-09-17 (B3-06) se
movieron tambien los de horarios y servicios. El repositorio solo hace
``flush``: el commit es de este service.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.staff.model import Schedule, Staff
from modules.staff.repository import StaffRepository

STAFF_KIND_PERSON = "person"
STAFF_KIND_RESOURCE = "resource"


class StaffService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = StaffRepository(db)

    async def create(
        self, data: dict[str, Any], store_id: str, service_public_ids: list[str]
    ) -> Staff:
        staff = await self.repo.create(data, store_id, service_public_ids)
        await self.db.commit()
        await self.db.refresh(staff)
        return staff

    async def update_profile(self, staff: Staff, **changes: Any) -> Staff:
        updated = await self.repo.update_profile(staff, **changes)
        await self.db.commit()
        await self.db.refresh(updated)
        return updated

    async def soft_delete(self, staff: Staff) -> None:
        await self.repo.soft_delete(staff)
        await self.db.commit()

    async def add_schedule(
        self, staff: Staff, schedule_data: dict[str, Any], store_id: str
    ) -> Schedule:
        schedule = await self.repo.add_schedule(staff, schedule_data, store_id)
        await self.db.commit()
        await self.db.refresh(schedule)
        return schedule

    async def update_schedule(
        self, staff: Staff, schedule: Schedule, cambios: dict[str, Any]
    ) -> Schedule:
        actualizado = await self.repo.update_schedule(staff, schedule, cambios)
        await self.db.commit()
        await self.db.refresh(actualizado)
        return actualizado

    async def delete_schedule(self, schedule: Schedule) -> None:
        await self.repo.delete_schedule(schedule)
        await self.db.commit()

    async def update_services(
        self, staff: Staff, service_public_ids: list[str]
    ) -> Staff:
        updated = await self.repo.update_services(staff, service_public_ids)
        await self.db.commit()
        await self.db.refresh(updated)
        return updated
