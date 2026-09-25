"""Alta, edicion y baja de personal, horarios y servicios: dueno de la transaccion.

El repositorio commiteaba por su cuenta (deuda declarada). Al agregar
``kind`` (persona o recurso) se movieron los commits de alta/edicion/baja aca,
como en el modulo de referencia ``appointments``; el 2026-09-17 (B3-06) se
movieron tambien los de horarios y servicios. El repositorio solo hace
``flush``: el commit es de este service.
"""

from __future__ import annotations

from typing import Any

import structlog
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from core.availability_cache import (
    AvailabilityCacheClient,
    invalidate_store_availability,
)
from modules.staff.model import Schedule, Staff
from modules.staff.repository import StaffRepository

logger = structlog.get_logger()

STAFF_KIND_PERSON = "person"
STAFF_KIND_RESOURCE = "resource"


class StaffService:
    """Dueno de la transaccion y de la invalidacion del cache de la agenda.

    El personal y sus franjas son uno de los dos insumos de la grilla, asi que
    todo camino de escritura de aca invalida la disponibilidad (AUD2-B3-05).
    La invalidacion va DESPUES del commit y es best-effort: un Redis caido no
    revierte lo ya guardado; en el peor caso el portal muestra lo viejo hasta
    que vencen los slots (``SLOTS_TTL_SECONDS``, 300 s).

    ``create`` es el unico camino que no invalida: un profesional recien
    creado no tiene franjas, asi que no aporta ni un horario a la grilla hasta
    que pasa por ``add_schedule``, que si invalida.
    """

    def __init__(
        self, db: AsyncSession, cache: AvailabilityCacheClient | None = None
    ) -> None:
        self.db = db
        self.repo = StaffRepository(db)
        self.cache = cache

    async def _invalidar_agenda(self, store_id: str | None) -> None:
        if self.cache is None or not store_id:
            return
        try:
            await invalidate_store_availability(self.cache, store_id)
        except RedisError as exc:
            logger.warning(
                "staff_cache_invalidation_failed",
                store_id=store_id,
                error_type=type(exc).__name__,
            )

    async def create(
        self, data: dict[str, Any], store_id: str, service_public_ids: list[str]
    ) -> Staff:
        staff = await self.repo.create(data, store_id, service_public_ids)
        await self.db.commit()
        await self.db.refresh(staff)
        return staff

    async def update_profile(self, staff: Staff, **changes: Any) -> Staff:
        store_id = staff.store_id
        updated = await self.repo.update_profile(staff, **changes)
        await self.db.commit()
        await self.db.refresh(updated)
        await self._invalidar_agenda(store_id)
        return updated

    async def soft_delete(self, staff: Staff) -> None:
        store_id = staff.store_id
        await self.repo.soft_delete(staff)
        await self.db.commit()
        await self._invalidar_agenda(store_id)

    async def add_schedule(
        self, staff: Staff, schedule_data: dict[str, Any], store_id: str
    ) -> Schedule:
        schedule = await self.repo.add_schedule(staff, schedule_data, store_id)
        await self.db.commit()
        await self.db.refresh(schedule)
        await self._invalidar_agenda(store_id)
        return schedule

    async def update_schedule(
        self, staff: Staff, schedule: Schedule, cambios: dict[str, Any]
    ) -> Schedule:
        store_id = schedule.store_id
        actualizado = await self.repo.update_schedule(staff, schedule, cambios)
        await self.db.commit()
        await self.db.refresh(actualizado)
        await self._invalidar_agenda(store_id)
        return actualizado

    async def delete_schedule(self, schedule: Schedule) -> None:
        store_id = schedule.store_id
        await self.repo.delete_schedule(schedule)
        await self.db.commit()
        await self._invalidar_agenda(store_id)

    async def update_services(
        self, staff: Staff, service_public_ids: list[str]
    ) -> Staff:
        store_id = staff.store_id
        updated = await self.repo.update_services(staff, service_public_ids)
        await self.db.commit()
        await self.db.refresh(updated)
        await self._invalidar_agenda(store_id)
        return updated
