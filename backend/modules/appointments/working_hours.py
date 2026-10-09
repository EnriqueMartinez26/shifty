"""Horario efectivo de los profesionales: el suyo o, sin franjas, el del local.

Decisiones del duenio D-20260929-01 y D-20260929-02 (docs/DECISIONES.md):

- La agenda usa las franjas del profesional (``schedules``).
- Un profesional SIN ninguna franja cargada (ningun dia) atiende en el
  horario comercial del local (``store_schedules``) ese dia de la semana.
- Uno que tiene franjas, pero ninguna ese dia, NO atiende ese dia: el local
  abierto no lo abre a el.

Es la UNICA fuente de esa regla: la grilla de disponibilidad
(``AvailabilityService.load_day_agenda``) y la validacion del alta y de la
reprogramacion (``PublicRepository.staff_can_take_range`` /
``_pick_staff_for_slot`` y la reprogramacion del panel) leen de aca. Antes
cada una leia ``schedules`` por su lado y un profesional sin franjas no tenia
agenda en ninguna (2026-09-29).

Consultas (regla 12): una sola para las franjas de todos los profesionales
pedidos, con un ``EXISTS`` que dice si tienen alguna franja en la semana, y
una segunda, solo si alguno cae al respaldo, para el horario del local.
Las franjas estan cargadas en hora ARGENTINA (regla 24): el dia de la semana
es el del dia LOCAL y la comparacion con un turno se hace en instantes.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time

from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from core.utils import ARGENTINA_TZ, ensure_utc_aware, local_to_utc
from modules.staff.model import Schedule, Staff
from modules.stores.model import StoreSchedule

Franja = tuple[time, time]


def resolve_effective_hours(
    own: dict[str, list[Franja]],
    with_any_schedule: set[str],
    staff_ids: Sequence[str],
    store_hours: list[Franja],
) -> dict[str, list[Franja]]:
    """Franjas del dia por profesional; lista vacia = ese dia no atiende.

    ``own``: las franjas propias de ESE dia. ``with_any_schedule``: quienes
    tienen al menos una franja en cualquier dia (esos nunca caen al local).
    """
    return {
        staff_id: (
            list(own.get(staff_id, []))
            if staff_id in with_any_schedule
            else list(store_hours)
        )
        for staff_id in staff_ids
    }


def franjas_cover(
    local_day: date, franjas: list[Franja], starts_at: datetime, ends_at: datetime
) -> bool:
    """Alguna franja de ese dia local contiene el rango COMPLETO? (AUD2-B1-03)

    Se comparan INSTANTES, no la hora del dia suelta: con ``time`` un turno
    que termina despues de la medianoche local "daba la vuelta" (23:30 + 60
    min queda en 00:30) y ``cierre >= fin`` se cumplia solo.
    """
    return any(
        local_to_utc(local_day, apertura) <= starts_at
        and ends_at <= local_to_utc(local_day, cierre)
        for apertura, cierre in franjas
    )


async def load_effective_hours(
    db: AsyncSession,
    store_id: str,
    local_day: date,
    staff_ids: Sequence[str] | None = None,
) -> dict[str, list[Franja]]:
    """Horario efectivo de ``local_day`` (dia calendario argentino).

    Sin ``staff_ids``: todos los profesionales ACTIVOS de la tienda (la grilla
    del dia). Con ``staff_ids``: esos, de la tienda (el alta ya los resolvio).
    """
    weekday = local_day.weekday()
    cualquier_dia = aliased(Schedule)
    tiene_franjas = (
        exists()
        .where(cualquier_dia.staff_id == Staff.id)
        .correlate(Staff)
        .label("has_schedule")
    )
    stmt = (
        select(Staff.id, tiene_franjas, Schedule.start_time, Schedule.end_time)
        .select_from(Staff)
        .outerjoin(
            Schedule,
            and_(Schedule.staff_id == Staff.id, Schedule.day_of_week == weekday),
        )
        .where(Staff.store_id == store_id)
        .order_by(Staff.id, Schedule.start_time, Schedule.id)
    )
    if staff_ids is None:
        stmt = stmt.where(Staff.is_active.is_(True))
    else:
        stmt = stmt.where(Staff.id.in_(list(staff_ids)))

    own: dict[str, list[Franja]] = {}
    with_any: set[str] = set()
    found: list[str] = []
    for staff_id, has_schedule, start_time, end_time in (await db.execute(stmt)).all():
        if staff_id not in own:
            own[staff_id] = []
            found.append(staff_id)
        if has_schedule:
            with_any.add(staff_id)
        if start_time is not None and end_time is not None:
            own[staff_id].append((start_time, end_time))

    store_hours: list[Franja] = []
    if any(staff_id not in with_any for staff_id in found):
        store_hours = [
            (row.open_time, row.close_time)
            for row in (
                await db.execute(
                    select(StoreSchedule.open_time, StoreSchedule.close_time)
                    .where(
                        StoreSchedule.store_id == store_id,
                        StoreSchedule.day_of_week == weekday,
                    )
                    .order_by(StoreSchedule.open_time)
                )
            ).all()
        ]
    return resolve_effective_hours(own, with_any, found, store_hours)


async def staff_ids_working_range(
    db: AsyncSession,
    store_id: str,
    staff_ids: Sequence[str],
    starts_at: datetime,
    ends_at: datetime,
) -> set[str]:
    """De ``staff_ids``, los que atienden el rango completo (horario efectivo).

    El dia es el dia LOCAL del inicio del turno (2026-09-10: comparar en UTC
    rechazaba las ultimas 3 horas de cada jornada).
    """
    if not staff_ids:
        return set()
    starts_utc = ensure_utc_aware(starts_at)
    ends_utc = ensure_utc_aware(ends_at)
    local_day = starts_utc.astimezone(ARGENTINA_TZ).date()
    hours = await load_effective_hours(db, store_id, local_day, staff_ids)
    return {
        staff_id
        for staff_id, franjas in hours.items()
        if franjas_cover(local_day, franjas, starts_utc, ends_utc)
    }


__all__ = [
    "Franja",
    "franjas_cover",
    "load_effective_hours",
    "resolve_effective_hours",
    "staff_ids_working_range",
]
