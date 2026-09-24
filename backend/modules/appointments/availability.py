"""
AvailabilityService — Cálculo de slots disponibles.

Incluye bloqueos de agenda (StaffBlock) en el cálculo:
un slot es libre solo si:
  - Está dentro del Schedule del staff ese día.
  - No solapa con ningún Appointment activo.
  - No solapa con ningún StaffBlock activo.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TypedDict, cast

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from core.availability_cache import SLOTS_TTL_SECONDS, resolve_slots_key
from core.utils import ARGENTINA_TZ, ensure_utc_aware, local_to_utc
from modules.appointments.model import Appointment
from modules.payments.service import ACTIVE_APPOINTMENT_STATUSES
from modules.services.model import Service
from modules.staff.model import Staff, Schedule, StaffBlock
from modules.stores.model import Store


class AvailabilitySlot(TypedDict):
    staff_id: str
    staff_name: str
    starts_at: str
    ends_at: str
    start_time: str
    end_time: str
    status: str
    reason: str | None


Range = tuple[datetime, datetime]

# Paso de la grilla de horarios: un slot empieza cada SLOT_STEP desde el
# inicio del horario del profesional.
SLOT_STEP = timedelta(minutes=15)


def _first_grid_start(origin: datetime, instant: datetime) -> datetime:
    """Primer inicio de la grilla (``origin`` + k * SLOT_STEP) en o despues de ``instant``."""
    if instant <= origin:
        return origin
    pasos = -((origin - instant) // SLOT_STEP)  # techo de la division
    return origin + pasos * SLOT_STEP


def free_window(
    start: datetime,
    end: datetime,
    *,
    window_start: datetime,
    window_end: datetime,
    obstacles: list[Range],
) -> Range:
    """Hueco libre que contiene al slot libre ``[start, end)``.

    Va desde el obstaculo anterior (o el inicio del horario) hasta el
    siguiente (o el fin). Los obstaculos son turnos ensanchados por el
    buffer, bloqueos y la ventana de antelacion minima.
    """
    free_from = max(
        [window_start] + [o_end for _o, o_end in obstacles if o_end <= start]
    )
    free_until = min(
        [window_end] + [o_start for o_start, _o in obstacles if o_start >= end]
    )
    return free_from, free_until


def leaves_unsellable_gap(
    start: datetime,
    duration: timedelta,
    *,
    free_from: datetime,
    free_until: datetime,
    grid_origin: datetime,
) -> bool:
    """El slot deja un hueco que ningun turno del servicio puede ocupar.

    Criterio de "strict gap filtering" (B1-01/B6-03, decision del brief:
    no ofrecer huecos irreservables, no esconder todo). La adyacencia se mide
    por paso de grilla real, no por igualdad de strings ISO:

    - Un slot pegado a un borde de su hueco (el primer inicio de grilla desde
      ``free_from``, o el ultimo que todavia entra antes de ``free_until``)
      siempre se ofrece: lo que sobra es menor que un paso y no se evita.
    - Uno del medio se ofrece si a cada lado todavia entra otro turno del
      mismo servicio alineado a la grilla.

    Antes se exigia que el fin de un slot coincidiera con el inicio de otro:
    con duraciones que no son multiplo de 15 (40, 50, 70 minutos) nunca
    pasaba y del dia solo quedaban el primer y el ultimo slot.
    """
    primer_inicio = _first_grid_start(grid_origin, free_from)
    pegado_al_inicio = start == primer_inicio
    pegado_al_fin = start + SLOT_STEP + duration > free_until
    if pegado_al_inicio or pegado_al_fin:
        return False
    entra_antes = primer_inicio + duration <= start
    entra_despues = (
        _first_grid_start(grid_origin, start + duration) + duration <= free_until
    )
    return not (entra_antes and entra_despues)


@dataclass
class _DayAgenda:
    """Todo lo que la grilla de un dia necesita, leido en lote (sin N+1)."""

    notice_hours: int
    buffer: timedelta
    min_bookable_time: datetime
    schedules: dict[str, list[Schedule]]
    booked: dict[str, list[Range]]
    blocks: dict[str, list[StaffBlock]]


class AvailabilityService:
    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis

    async def get_available_slots(
        self,
        store_id: str,
        service_public_id: str,
        search_date: date,
        force_all: bool = False,
        hide_private_reasons: bool = False,
    ) -> list[AvailabilitySlot]:
        """
        Calcula los slots disponibles para un servicio en una fecha dada,
        respetando horarios, turnos ocupados y bloqueos de agenda.

        Partida en pasos (B1-12, antes 250 lineas); el orden de las consultas
        y la salida son los mismos de siempre
        (``tests/integration/test_caracterizacion_disponibilidad.py``).
        """
        # 1. Caché: generacion de la tienda (B6-08) + version del dia (B7-09).
        cache_key = await resolve_slots_key(
            self.redis,
            store_id,
            search_date,
            service_public_id,
            force_all=force_all,
            hide_private_reasons=hide_private_reasons,
        )
        cached = await self.redis.get(cache_key)
        if cached:
            return cast(list[AvailabilitySlot], json.loads(cached))

        # 2. Servicio activo de la tienda (sin servicio no se cachea nada).
        svc_res = await self.db.execute(
            select(Service).where(
                Service.public_id == service_public_id,
                Service.store_id == store_id,
                Service.is_active.is_(True),
            )
        )
        service = svc_res.scalar_one_or_none()
        if not service:
            return []

        # 3. Staff que realiza el servicio.
        staff_members = await self._staff_for_service(store_id, service_public_id)
        if not staff_members:
            await self.redis.setex(cache_key, SLOTS_TTL_SECONDS, "[]")
            return []

        # 4 a 6. Reglas de la tienda, horarios, turnos y bloqueos del dia.
        agenda = await self._load_day(
            store_id, [member.id for member in staff_members], search_date
        )
        duration = timedelta(minutes=service.duration_minutes)

        # 7. Grilla por profesional y por franja horaria.
        all_slots: list[AvailabilitySlot] = []
        for staff in staff_members:
            for sched in agenda.schedules.get(staff.id, []):
                all_slots.extend(
                    _schedule_slots(
                        staff,
                        sched,
                        search_date,
                        duration,
                        agenda,
                        force_all=force_all,
                        hide_private_reasons=hide_private_reasons,
                    )
                )

        # 8. Caché por 5 minutos
        await self.redis.setex(cache_key, SLOTS_TTL_SECONDS, json.dumps(all_slots))
        return all_slots

    async def _staff_for_service(
        self, store_id: str, service_public_id: str
    ) -> list[Staff]:
        staff_res = await self.db.execute(
            select(Staff)
            .options(selectinload(Staff.services))
            .where(
                Staff.store_id == store_id,
                Staff.is_active.is_(True),
            )
        )
        return [
            member
            for member in staff_res.scalars().all()
            if service_public_id in (member.service_ids or [])
        ]

    async def _load_day(
        self, store_id: str, staff_ids: list[str], search_date: date
    ) -> _DayAgenda:
        """Reglas de la tienda y agenda del dia de todos los profesionales.

        La fecha que pide el cliente es un dia calendario argentino, no una
        ventana UTC: se traduce a sus limites reales en UTC. Una consulta por
        tabla con ``in_()`` (regla 12).
        """
        day_start = local_to_utc(search_date, time.min)
        day_end = local_to_utc(search_date, time.max)

        store_res = await self.db.execute(select(Store).where(Store.id == store_id))
        store = store_res.scalar_one_or_none()
        notice_hours = getattr(store, "min_booking_notice_hours", 2)
        # Hueco obligatorio entre turnos: un slot no se ofrece si queda a menos
        # de 'buffer' de un turno vecino. Debe coincidir con la regla que aplica
        # el alta (get_conflicting_appointment), o el cliente veria horarios que
        # despues se rechazan.
        buffer = timedelta(minutes=getattr(store, "buffer_minutes", 0) or 0)

        from core.utils import now_utc

        min_bookable_time = now_utc() + timedelta(hours=notice_hours)

        schedules_res = await self.db.execute(
            select(Schedule).where(
                Schedule.staff_id.in_(staff_ids),
                Schedule.day_of_week == search_date.weekday(),
            )
        )
        schedules: dict[str, list[Schedule]] = {}
        for schedule in schedules_res.scalars().all():
            schedules.setdefault(schedule.staff_id, []).append(schedule)

        booked, blocks = await self._load_occupancy(
            store_id, staff_ids, day_start, day_end, buffer=buffer
        )
        return _DayAgenda(
            notice_hours=notice_hours,
            buffer=buffer,
            min_bookable_time=min_bookable_time,
            schedules=schedules,
            booked=booked,
            blocks=blocks,
        )

    async def _load_occupancy(
        self,
        store_id: str,
        staff_ids: list[str],
        day_start: datetime,
        day_end: datetime,
        *,
        buffer: timedelta,
    ) -> tuple[dict[str, list[Range]], dict[str, list[StaffBlock]]]:
        """Turnos activos y bloqueos del dia, una consulta cada uno.

        Los turnos se traen por SOLAPAMIENTO, igual que los bloqueos
        (AUD2-B1-13): antes se filtraban por ``starts_at`` dentro de la
        ventana, asi que uno que empieza el dia local anterior y termina
        adentro del dia consultado no entraba en ``booked`` y su slot salia
        ``available`` para despues ser rechazado con 409. La ventana se
        ensancha por ``buffer`` porque el obstaculo real que arma
        ``_schedule_slots`` es el turno mas el hueco obligatorio a cada lado.

        Las dos consultas llevan la tienda y las dos cotas de
        ``appointment_overlap`` / ``active_block_overlap`` (F1-13): antes
        recorrian toda la historia de los profesionales en cada consulta de
        disponibilidad sin cache.
        """
        from sqlalchemy.orm import joinedload

        from modules.appointments.repository import (
            active_block_overlap,
            appointment_overlap,
        )

        appt_res = await self.db.execute(
            select(Appointment)
            .options(joinedload(Appointment.service))
            .where(
                and_(
                    Appointment.staff_id.in_(staff_ids),
                    Appointment.status.in_(list(ACTIVE_APPOINTMENT_STATUSES)),
                    appointment_overlap(store_id, day_start - buffer, day_end + buffer),
                )
            )
        )
        # Rangos ocupados normalizados a UTC aware: SQLite devuelve naive y la
        # comparacion con los slots (aware) explotaba.
        booked: dict[str, list[Range]] = {}
        for appointment in appt_res.scalars().all():
            booked.setdefault(appointment.staff_id, []).append(
                (
                    ensure_utc_aware(appointment.starts_at),
                    ensure_utc_aware(appointment.ends_at),
                )
            )

        block_res = await self.db.execute(
            select(StaffBlock).where(
                and_(
                    StaffBlock.staff_id.in_(staff_ids),
                    active_block_overlap(store_id, day_start, day_end),
                )
            )
        )
        blocks: dict[str, list[StaffBlock]] = {}
        for block in block_res.scalars().all():
            blocks.setdefault(block.staff_id, []).append(block)

        return booked, blocks


def _schedule_slots(
    staff: Staff,
    sched: Schedule,
    search_date: date,
    duration: timedelta,
    agenda: _DayAgenda,
    *,
    force_all: bool,
    hide_private_reasons: bool,
) -> list[AvailabilitySlot]:
    """Slots (granularidad SLOT_STEP) de una franja horaria de un profesional."""
    booked = agenda.booked.get(staff.id, [])
    blocks = agenda.blocks.get(staff.id, [])
    # Lo que corta un hueco libre, para el filtro de huecos (B1-01).
    obstacles: list[Range] = [
        (appt_start - agenda.buffer, appt_end + agenda.buffer)
        for appt_start, appt_end in booked
    ] + [(ensure_utc_aware(b.starts_at), ensure_utc_aware(b.ends_at)) for b in blocks]

    # El horario del staff esta cargado en hora local argentina.
    current = local_to_utc(search_date, sched.start_time)
    end = local_to_utc(search_date, sched.end_time)
    grid_origin = current
    # Lo anterior a la antelacion minima tampoco se puede vender.
    sched_obstacles = obstacles + (
        [(current, agenda.min_bookable_time)]
        if agenda.min_bookable_time > current
        else []
    )

    slots: list[AvailabilitySlot] = []
    while current + duration <= end:
        slot_end = current + duration
        status, reason = _slot_status(
            current,
            slot_end,
            booked,
            blocks,
            agenda,
            hide_private_reasons=hide_private_reasons,
        )
        # Sin force_all no se ofrece un slot libre que deje un hueco
        # invendible (B1-01). Los ocupados/bloqueados se muestran igual:
        # informan, no se venden.
        if not force_all and status == "available":
            free_from, free_until = free_window(
                current,
                slot_end,
                window_start=grid_origin,
                window_end=end,
                obstacles=sched_obstacles,
            )
            if leaves_unsellable_gap(
                current,
                duration,
                free_from=free_from,
                free_until=free_until,
                grid_origin=grid_origin,
            ):
                current += SLOT_STEP
                continue
        slots.append(_slot(staff, current, slot_end, status, reason))
        current += SLOT_STEP
    return slots


def _slot_status(
    current: datetime,
    slot_end: datetime,
    booked: list[Range],
    blocks: list[StaffBlock],
    agenda: _DayAgenda,
    *,
    hide_private_reasons: bool,
) -> tuple[str, str | None]:
    """Turno (ensanchado por el buffer) > bloqueo > antelacion > libre."""
    buffer = agenda.buffer
    if any(
        not (slot_end <= appt_start - buffer or current >= appt_end + buffer)
        for appt_start, appt_end in booked
    ):
        return "booked", None
    overlapping_block = next(
        (b for b in blocks if b.overlaps_with(current, slot_end)), None
    )
    if overlapping_block:
        return "blocked", (
            "No disponible" if hide_private_reasons else overlapping_block.note
        )
    # Forcing Function: min_booking_notice
    if current < agenda.min_bookable_time:
        return "blocked", f"Requiere {agenda.notice_hours}h de antelación"
    return "available", None


def _slot(
    staff: Staff, current: datetime, slot_end: datetime, status: str, reason: str | None
) -> AvailabilitySlot:
    return {
        "staff_id": staff.public_id,
        "staff_name": staff.display_name,
        # starts_at/ends_at: instante en UTC (fuente de verdad para reservar).
        # start_time/end_time: lo que ve el cliente, en hora argentina. Antes
        # salian en UTC y el front mostraba "12:00" para un turno de 09:00
        # (2026-09-10).
        "starts_at": current.isoformat(),
        "ends_at": slot_end.isoformat(),
        "start_time": current.astimezone(ARGENTINA_TZ)
        .time()
        .isoformat(timespec="seconds"),
        "end_time": slot_end.astimezone(ARGENTINA_TZ)
        .time()
        .isoformat(timespec="seconds"),
        "status": status,
        "reason": reason,
    }
