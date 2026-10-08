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
from core.exceptions import AppException
from modules.staff.model import Schedule, Staff
from modules.staff.repository import StaffRepository
from modules.users.model import User

logger = structlog.get_logger()

STAFF_KIND_PERSON = "person"
STAFF_KIND_RESOURCE = "resource"


def _account_display_name(account: User) -> str:
    """Nombre con el que figura la cuenta si no eligio uno (minimo 2 letras)."""
    nombre = (account.full_name or "").strip()
    if len(nombre) >= 2:
        return nombre[:100]
    return account.email.split("@", 1)[0][:100].ljust(2, "_")


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

    async def add_self(
        self,
        account: User,
        *,
        display_name: str | None,
        service_public_ids: list[str],
    ) -> Staff:
        """La cuenta que llama se agrega como profesional (decision de Mateo).

        El dueno tambien atiende, con su nombre y su misma cuenta: sin usuario
        nuevo ni email repetido (regla 16) y sin cambiar su rol. Si ya tuvo
        ficha y se quito de la agenda, se reactiva la misma. Solo sobre uno
        mismo: no hay forma de volver reservable a OTRA cuenta por aca.
        """
        existing = await self.repo.get_by_id(
            account.id, account.store_id, include_global_admins=True
        )
        if existing is not None and existing.is_active:
            raise AppException(
                message="Ya figurás como profesional.",
                http_status=409,
                error_code="STAFF_SELF_ALREADY_EXISTS",
            )
        nombre = (display_name or "").strip() or _account_display_name(account)
        if existing is not None:
            staff = await self.repo.reactivate(
                existing, account, nombre, service_public_ids
            )
        else:
            staff = await self.repo.create_for_account(
                account, nombre, service_public_ids
            )
        await self.db.commit()
        await self._invalidar_agenda(account.store_id)
        return staff

    async def update_profile(self, staff: Staff, **changes: Any) -> Staff:
        store_id = staff.store_id
        updated = await self.repo.update_profile(staff, **changes)
        await self.db.commit()
        await self.db.refresh(updated)
        await self._invalidar_agenda(store_id)
        return updated

    async def soft_delete(self, staff: Staff, *, keep_login: bool = False) -> None:
        store_id = staff.store_id
        await self.repo.soft_delete(staff, keep_login=keep_login)
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
