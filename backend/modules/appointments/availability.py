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
from datetime import date, datetime, time, timedelta, timezone
from typing import TypedDict, cast

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select

import structlog

import core.utils as core_utils
from core.availability_cache import (
    DAY_AGENDA_TTL_SECONDS,
    SLOTS_TTL_SECONDS,
    AvailabilityCacheClient,
    AvailabilityKeys,
    resolve_availability_keys,
)
from core.redis import REDIS_UNAVAILABLE_ERRORS
from core.utils import ARGENTINA_TZ, ensure_utc_aware, local_to_utc
from modules.appointments.model import Appointment
from modules.payments.service import ACTIVE_APPOINTMENT_STATUSES
from modules.services.model import Service
from modules.staff.model import Schedule, Staff, StaffBlock, StaffServiceModel
from modules.stores.model import Store


logger = structlog.get_logger()


def _log_cache_unavailable(operation: str, exc: Exception) -> None:
    """Un warning por request: si la lectura falla, la escritura no se intenta.

    Solo el tipo de error (PV-22): el texto de redis-py puede traer la URL.
    """
    logger.warning(
        "availability_cache_unavailable",
        operation=operation,
        error_type=type(exc).__name__,
    )


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


@dataclass(frozen=True)
class StoreRules:
    """Reglas de la tienda que entran en la grilla (antelacion y buffer).

    El router publico ya las leyo en columnas al resolver la tienda (F3-02):
    se pasan para no volver a leer la tienda. Sin ellas (panel) se leen aca.
    """

    notice_hours: int
    buffer_minutes: int


@dataclass(frozen=True)
class _StaffRef:
    """Lo unico del profesional que usa la grilla (sin la entidad ORM)."""

    id: str
    display_name: str

    @property
    def public_id(self) -> str:
        # Mismo valor que ``Staff.public_id`` (el id).
        return self.id


@dataclass(frozen=True)
class _Block:
    starts_at: datetime
    ends_at: datetime
    note: str

    def overlaps_with(self, starts_at: datetime, ends_at: datetime) -> bool:
        return self.starts_at < ends_at and self.ends_at > starts_at


@dataclass
class _DayAgenda:
    """La agenda cruda de un dia de la tienda: todo lo que la grilla necesita.

    Es lo que guarda el nivel 2 del cache (F3-02) y sirve para CUALQUIER
    servicio: los slots de un servicio se derivan en memoria con su duracion
    y sus profesionales. ``min_bookable_time`` NO se guarda: depende de
    "ahora" y se calcula al derivar.
    """

    notice_hours: int
    buffer: timedelta
    schedules: dict[str, list[tuple[time, time]]]
    booked: dict[str, list[Range]]
    blocks: dict[str, list[_Block]]
    min_bookable_time: datetime = datetime.min.replace(tzinfo=timezone.utc)

    def to_json(self) -> str:
        return json.dumps(
            {
                "notice_hours": self.notice_hours,
                "buffer_minutes": int(self.buffer.total_seconds() // 60),
                "schedules": {
                    staff_id: [[a.isoformat(), b.isoformat()] for a, b in franjas]
                    for staff_id, franjas in self.schedules.items()
                },
                "booked": {
                    staff_id: [[a.isoformat(), b.isoformat()] for a, b in rangos]
                    for staff_id, rangos in self.booked.items()
                },
                "blocks": {
                    staff_id: [
                        [b.starts_at.isoformat(), b.ends_at.isoformat(), b.note]
                        for b in bloqueos
                    ]
                    for staff_id, bloqueos in self.blocks.items()
                },
            }
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> "_DayAgenda":
        data = json.loads(raw)
        return cls(
            notice_hours=int(data["notice_hours"]),
            buffer=timedelta(minutes=int(data["buffer_minutes"])),
            schedules={
                staff_id: [
                    (time.fromisoformat(a), time.fromisoformat(b)) for a, b in franjas
                ]
                for staff_id, franjas in data["schedules"].items()
            },
            booked={
                staff_id: [
                    (datetime.fromisoformat(a), datetime.fromisoformat(b))
                    for a, b in rangos
                ]
                for staff_id, rangos in data["booked"].items()
            },
            blocks={
                staff_id: [
                    _Block(datetime.fromisoformat(a), datetime.fromisoformat(b), note)
                    for a, b, note in bloqueos
                ]
                for staff_id, bloqueos in data["blocks"].items()
            },
        )


class AvailabilityService:
    def __init__(self, db: AsyncSession, redis: AvailabilityCacheClient) -> None:
        self.db = db
        self.redis = redis

    async def get_available_slots(
        self,
        store_id: str,
        service_public_id: str,
        search_date: date,
        force_all: bool = False,
        hide_private_reasons: bool = False,
        store_rules: StoreRules | None = None,
    ) -> list[AvailabilitySlot]:
        """
        Calcula los slots disponibles para un servicio en una fecha dada,
        respetando horarios, turnos ocupados y bloqueos de agenda.

        Dos niveles de cache bajo la misma generacion + version (F3-02): los
        slots del servicio y, debajo, la agenda cruda del dia de la tienda.
        La salida es la de siempre
        (``tests/integration/test_caracterizacion_disponibilidad.py``).
        """
        # 1. Claves vigentes: generacion de la tienda (B6-08) + version del
        # dia (B7-09), en un pipeline (F3-09). Un Redis caido o lleno es un
        # MISS (F1-10): se calcula desde la base y no se escribe el cache
        # (``keys`` queda en None).
        keys: AvailabilityKeys | None
        try:
            keys = await resolve_availability_keys(
                self.redis,
                store_id,
                search_date,
                service_public_id,
                force_all=force_all,
                hide_private_reasons=hide_private_reasons,
            )
            cached = await self.redis.get(keys.slots)
        except REDIS_UNAVAILABLE_ERRORS as exc:
            _log_cache_unavailable("read", exc)
            keys, cached = None, None
        if cached:
            return cast(list[AvailabilitySlot], json.loads(cached))

        # 2. Servicio activo de la tienda y sus profesionales, una consulta
        # (sin servicio no se cachea nada).
        found = await self._service_and_staff(store_id, service_public_id)
        if found is None:
            return []
        duration, staff_members = found
        if not staff_members:
            await self._write_cache(keys, slots="[]")
            return []

        # 3. Agenda cruda del dia: del nivel 2 o de la base.
        agenda, agenda_json = await self._day_agenda(
            keys, store_id, search_date, store_rules
        )
        agenda.min_bookable_time = core_utils.now_utc() + timedelta(
            hours=agenda.notice_hours
        )

        # 4. Grilla por profesional y por franja horaria.
        all_slots: list[AvailabilitySlot] = []
        for staff in staff_members:
            for franja in agenda.schedules.get(staff.id, []):
                all_slots.extend(
                    _schedule_slots(
                        staff,
                        franja,
                        search_date,
                        duration,
                        agenda,
                        force_all=force_all,
                        hide_private_reasons=hide_private_reasons,
                    )
                )

        # 5. Cache por 5 minutos (y la agenda, si se leyo de la base).
        await self._write_cache(keys, slots=json.dumps(all_slots), agenda=agenda_json)
        return all_slots

    async def _write_cache(
        self,
        keys: AvailabilityKeys | None,
        *,
        slots: str,
        agenda: str | None = None,
    ) -> None:
        """Escribe los slots (y la agenda) en una ida y vuelta.

        Sin claves (lectura caida) o con Redis caido, no: un solo warning.
        """
        if keys is None:
            return
        try:
            pipe = self.redis.pipeline(transaction=False)
            if agenda is not None:
                pipe.setex(keys.day_agenda, DAY_AGENDA_TTL_SECONDS, agenda)
            pipe.setex(keys.slots, SLOTS_TTL_SECONDS, slots)
            await pipe.execute()
        except REDIS_UNAVAILABLE_ERRORS as exc:
            _log_cache_unavailable("write", exc)

    async def _service_and_staff(
        self, store_id: str, service_public_id: str
    ) -> tuple[timedelta, list[_StaffRef]] | None:
        """Duracion del servicio y sus profesionales activos, en UNA consulta.

        ``None`` si el servicio no existe, es de otra tienda o esta inactivo.
        LEFT JOIN sobre ``staff_services`` filtrado por el servicio y la
        tienda: un servicio sin profesionales da una fila con el profesional
        en NULL. Columnas, no entidades: antes era ``select(Staff)`` de toda
        la tienda con sus ``services`` y ``schedules`` en cascada, filtrado
        en memoria (y un ``Staff`` cargado con la coleccion es justo lo que
        advierte AUD2-B6-02).
        """
        rows = (
            await self.db.execute(
                select(Service.duration_minutes, Staff.id, Staff.display_name)
                .select_from(Service)
                .outerjoin(
                    StaffServiceModel, StaffServiceModel.service_id == Service.id
                )
                .outerjoin(
                    Staff,
                    and_(
                        Staff.id == StaffServiceModel.staff_id,
                        Staff.store_id == store_id,
                        Staff.is_active.is_(True),
                    ),
                )
                .where(
                    Service.public_id == service_public_id,
                    Service.store_id == store_id,
                    Service.is_active.is_(True),
                )
                .order_by(Staff.id)
            )
        ).all()
        if not rows:
            return None
        duration = timedelta(minutes=rows[0].duration_minutes)
        staff = [
            _StaffRef(id=row.id, display_name=row.display_name)
            for row in rows
            if row.id is not None
        ]
        return duration, staff

    async def _day_agenda(
        self,
        keys: AvailabilityKeys | None,
        store_id: str,
        search_date: date,
        store_rules: StoreRules | None,
    ) -> tuple[_DayAgenda, str | None]:
        """Agenda del dia del nivel 2; si no esta, de la base.

        Devuelve tambien el JSON a escribir cuando salio de la base (``None``
        si salio del cache o si no hay claves).
        """
        if keys is not None:
            try:
                raw = await self.redis.get(keys.day_agenda)
            except REDIS_UNAVAILABLE_ERRORS as exc:
                _log_cache_unavailable("read", exc)
                raw = None
                keys = None
            if raw:
                return _DayAgenda.from_json(raw), None
        agenda = await self.load_day_agenda(store_id, search_date, store_rules)
        return agenda, (agenda.to_json() if keys is not None else None)

    async def load_day_agenda(
        self, store_id: str, search_date: date, store_rules: StoreRules | None = None
    ) -> _DayAgenda:
        """Reglas de la tienda y agenda del dia de TODOS sus profesionales.

        La fecha que pide el cliente es un dia calendario argentino, no una
        ventana UTC: se traduce a sus limites reales en UTC. Una consulta por
        tabla, en columnas (regla 12); sin horarios ese dia no hay nada que
        ocupar y no se leen turnos ni bloqueos.
        """
        if store_rules is None:
            store_rules = await self._store_rules(store_id)
        # Hueco obligatorio entre turnos: un slot no se ofrece si queda a menos
        # de 'buffer' de un turno vecino. Debe coincidir con la regla que aplica
        # el alta (get_conflicting_appointment), o el cliente veria horarios que
        # despues se rechazan.
        buffer = timedelta(minutes=store_rules.buffer_minutes)

        schedules_res = await self.db.execute(
            select(Schedule.staff_id, Schedule.start_time, Schedule.end_time)
            .join(Staff, Staff.id == Schedule.staff_id)
            .where(
                Staff.store_id == store_id,
                Staff.is_active.is_(True),
                Schedule.day_of_week == search_date.weekday(),
            )
            .order_by(Schedule.staff_id, Schedule.start_time, Schedule.id)
        )
        schedules: dict[str, list[tuple[time, time]]] = {}
        for staff_id, start_time, end_time in schedules_res.all():
            schedules.setdefault(staff_id, []).append((start_time, end_time))

        booked: dict[str, list[Range]] = {}
        blocks: dict[str, list[_Block]] = {}
        if schedules:
            booked, blocks = await self._load_occupancy(
                store_id,
                list(schedules),
                local_to_utc(search_date, time.min),
                local_to_utc(search_date, time.max),
                buffer=buffer,
            )
        return _DayAgenda(
            notice_hours=store_rules.notice_hours,
            buffer=buffer,
            schedules=schedules,
            booked=booked,
            blocks=blocks,
        )

    async def _store_rules(self, store_id: str) -> StoreRules:
        """Antelacion y buffer de la tienda, en columnas (sin sus horarios)."""
        row = (
            await self.db.execute(
                select(Store.min_booking_notice_hours, Store.buffer_minutes).where(
                    Store.id == store_id
                )
            )
        ).one_or_none()
        if row is None:
            return StoreRules(notice_hours=2, buffer_minutes=0)
        return StoreRules(
            notice_hours=row.min_booking_notice_hours,
            buffer_minutes=row.buffer_minutes or 0,
        )

    async def _load_occupancy(
        self,
        store_id: str,
        staff_ids: list[str],
        day_start: datetime,
        day_end: datetime,
        *,
        buffer: timedelta,
    ) -> tuple[dict[str, list[Range]], dict[str, list[_Block]]]:
        """Turnos activos y bloqueos del dia, una consulta cada uno, en columnas.

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
        disponibilidad sin cache. Solo las columnas que usa la grilla (F3-02):
        antes el turno venia con su servicio en JOIN, que nadie leia.
        """
        from modules.appointments.repository import (
            active_block_overlap,
            appointment_overlap,
        )

        appt_res = await self.db.execute(
            select(Appointment.staff_id, Appointment.starts_at, Appointment.ends_at)
            .where(
                and_(
                    Appointment.staff_id.in_(staff_ids),
                    Appointment.status.in_(list(ACTIVE_APPOINTMENT_STATUSES)),
                    appointment_overlap(store_id, day_start - buffer, day_end + buffer),
                )
            )
            .order_by(Appointment.starts_at, Appointment.id)
        )
        # Rangos ocupados normalizados a UTC aware: SQLite devuelve naive y la
        # comparacion con los slots (aware) explotaba.
        booked: dict[str, list[Range]] = {}
        for staff_id, starts_at, ends_at in appt_res.all():
            booked.setdefault(staff_id, []).append(
                (ensure_utc_aware(starts_at), ensure_utc_aware(ends_at))
            )

        block_res = await self.db.execute(
            select(
                StaffBlock.staff_id,
                StaffBlock.start_time,
                StaffBlock.end_time,
                StaffBlock.reason,
            )
            .where(
                and_(
                    StaffBlock.staff_id.in_(staff_ids),
                    active_block_overlap(store_id, day_start, day_end),
                )
            )
            .order_by(StaffBlock.start_time, StaffBlock.id)
        )
        blocks: dict[str, list[_Block]] = {}
        for staff_id, starts_at, ends_at, reason in block_res.all():
            blocks.setdefault(staff_id, []).append(
                _Block(ensure_utc_aware(starts_at), ensure_utc_aware(ends_at), reason)
            )

        return booked, blocks


def _schedule_slots(
    staff: _StaffRef,
    franja: tuple[time, time],
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
    ] + [(b.starts_at, b.ends_at) for b in blocks]

    # El horario del staff esta cargado en hora local argentina.
    current = local_to_utc(search_date, franja[0])
    end = local_to_utc(search_date, franja[1])
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
    blocks: list[_Block],
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
    staff: _StaffRef,
    current: datetime,
    slot_end: datetime,
    status: str,
    reason: str | None,
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
