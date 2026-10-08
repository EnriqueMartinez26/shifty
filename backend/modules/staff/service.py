"""Alta, edicion y baja de personal, horarios y servicios: dueno de la transaccion.

El repositorio commiteaba por su cuenta (deuda declarada). Al agregar
``kind`` (persona o recurso) se movieron los commits de alta/edicion/baja aca,
como en el modulo de referencia ``appointments``; el 2026-09-17 (B3-06) se
movieron tambien los de horarios y servicios. El repositorio solo hace
``flush``: el commit es de este service.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import structlog
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from core.availability_cache import (
    AvailabilityCacheClient,
    invalidate_store_availability,
)
from core.exceptions import ScheduleOverlapException
from modules.staff.model import Schedule, Staff
from modules.staff.repository import StaffRepository

logger = structlog.get_logger()

STAFF_KIND_PERSON = "person"
STAFF_KIND_RESOURCE = "resource"


def first_overlapping_day(franjas: Sequence[dict[str, Any]]) -> int | None:
    """Primer dia (0 = lunes) con dos franjas que se pisan, o ``None``.

    Misma regla que ``StaffRepository._assert_no_overlap``: dos franjas se
    pisan si ``inicio < fin_de_la_otra`` y ``fin > inicio_de_la_otra``; las
    que solo se tocan en el borde (09-13 y 13-17) son validas.
    """
    por_dia: dict[int, list[tuple[Any, Any]]] = {}
    for franja in franjas:
        por_dia.setdefault(franja["day_of_week"], []).append(
            (franja["start_time"], franja["end_time"])
        )
    for dia in sorted(por_dia):
        ordenadas = sorted(por_dia[dia])
        for (_, fin_anterior), (inicio, _) in zip(ordenadas, ordenadas[1:]):
            if inicio < fin_anterior:
                return dia
    return None


class StaffService:
    """Dueno de la transaccion y de la invalidacion del cache de la agenda.

    El personal y sus franjas son uno de los dos insumos de la grilla, asi que
    todo camino de escritura de aca invalida la disponibilidad (AUD2-B3-05).
    La invalidacion va DESPUES del commit y es best-effort: un Redis caido no
    revierte lo ya guardado; en el peor caso el portal muestra lo viejo hasta
    que vencen los slots (``SLOTS_TTL_SECONDS``, 300 s).

    ``create`` tambien invalida desde el 2026-09-29: un profesional recien
    creado no tiene franjas y por eso atiende en el horario del local
    (D-20260929-01/02, ``appointments.working_hours``); con los servicios que
    ya trae aporta horarios a la grilla desde el alta.
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
        await self._invalidar_agenda(store_id)
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

    async def replace_schedules(
        self, staff: Staff, franjas: list[dict[str, Any]]
    ) -> list[Schedule]:
        """Reemplaza la semana entera del profesional en UNA transaccion.

        Armar la semana con una llamada por franja dejaba estados intermedios
        a la vista del portal: con la primera franja guardada el profesional
        dejaba de atender todos los demas dias (D-20260929-01). Lista vacia =
        vuelve al horario del local. Una superposicion rechaza el cuerpo
        entero antes de tocar nada.
        """
        superpuesto = first_overlapping_day(franjas)
        if superpuesto is not None:
            raise ScheduleOverlapException(day_of_week=superpuesto)
        store_id = staff.store_id
        await self.repo.lock_staff(staff)
        nuevas = await self.repo.replace_schedules(staff, franjas)
        await self.db.commit()
        await self._invalidar_agenda(store_id)
        return sorted(nuevas, key=lambda f: (f.day_of_week, f.start_time))

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
