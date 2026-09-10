"""Alta, edicion y baja de personal: dueno de la transaccion.

El repositorio commiteaba por su cuenta (deuda declarada). Al agregar
``kind`` (persona o recurso) se movieron los commits de alta/edicion/baja aca,
como en el modulo de referencia ``appointments``. Los endpoints de horarios y
servicios del personal siguen commiteando en el repositorio: deuda que queda
declarada, no extendida.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.staff.model import Staff
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
