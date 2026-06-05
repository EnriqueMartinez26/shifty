"""
AvailabilityService — Cálculo de slots disponibles.

Incluye bloqueos de agenda (StaffBlock) en el cálculo:
un slot es libre solo si:
  - Está dentro del Schedule del staff ese día.
  - No solapa con ningún Appointment activo.
  - No solapa con ningún StaffBlock activo.
"""
import json
from datetime import date, datetime, timedelta, time

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select

from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.service import ACTIVE_APPOINTMENT_STATUSES
from modules.services.model import Service
from modules.staff.model import Staff, Schedule, StaffBlock
from modules.stores.model import Store


class AvailabilityService:
    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis

    async def get_available_slots(
        self,
        store_id: int,
        service_public_id: str,
        search_date: date,
        force_all: bool = False,
        hide_private_reasons: bool = False,
    ) -> list[dict]:
        """
        Calcula los slots disponibles para un servicio en una fecha dada,
        respetando horarios, turnos ocupados y bloqueos de agenda.
        """
        # 1. Caché check ----------------------------------------------------
        cache_key = f"availability:{store_id}:{service_public_id}:{search_date.isoformat()}:{int(force_all)}:{int(hide_private_reasons)}"
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)

        # 2. Resolver servicio -----------------------------------------------
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

        duration = timedelta(minutes=service.duration_minutes)
        from datetime import timezone as _tz
        day_start = datetime.combine(search_date, time.min).replace(tzinfo=_tz.utc)
        day_end   = datetime.combine(search_date, time.max).replace(tzinfo=_tz.utc)

        # 3. Staff que realiza el servicio ------------------------------------
        staff_res = await self.db.execute(
            select(Staff)
            .where(
                Staff.store_id == store_id,
                Staff.is_active.is_(True),
            )
        )
        all_store_staff = staff_res.scalars().all()
        staff_members = [
            member
            for member in all_store_staff
            if service_public_id in (member.service_ids or [])
        ]
        if not staff_members:
            await self.redis.setex(cache_key, 300, "[]")
            return []
        staff_ids = [member.id for member in staff_members]

        # 4. Resolver reglas del Store ----------------------------------------
        store_res = await self.db.execute(select(Store).where(Store.id == store_id))
        store = store_res.scalar_one_or_none()
        notice_hours = getattr(store, "min_booking_notice_hours", 2)
        
        from core.utils import now_utc
        from datetime import timezone
        min_bookable_time = now_utc() + timedelta(hours=notice_hours)

        all_slots: list[dict] = []
        day_of_week = search_date.weekday()

        schedules_res = await self.db.execute(
            select(Schedule).where(
                Schedule.staff_id.in_(staff_ids),
                Schedule.day_of_week == day_of_week,
            )
        )
        schedules_by_staff: dict[str, list[Schedule]] = {}
        for schedule in schedules_res.scalars().all():
            schedules_by_staff.setdefault(schedule.staff_id, []).append(schedule)

        from sqlalchemy.orm import joinedload
        appt_res = await self.db.execute(
            select(Appointment).options(joinedload(Appointment.service)).where(
                and_(
                    Appointment.staff_id.in_(staff_ids),
                    Appointment.status.in_(list(ACTIVE_APPOINTMENT_STATUSES)),
                    Appointment.starts_at >= day_start,
                    Appointment.starts_at < day_end,
                )
            )
        )
        booked_by_staff: dict[str, list[Appointment]] = {}
        for appointment in appt_res.scalars().all():
            booked_by_staff.setdefault(appointment.staff_id, []).append(appointment)

        block_res = await self.db.execute(
            select(StaffBlock).where(
                and_(
                    StaffBlock.staff_id.in_(staff_ids),
                    StaffBlock.is_active.is_(True),
                    StaffBlock.starts_at < day_end,
                    StaffBlock.ends_at > day_start,
                )
            )
        )
        blocks_by_staff: dict[str, list[StaffBlock]] = {}
        for block in block_res.scalars().all():
            blocks_by_staff.setdefault(block.staff_id, []).append(block)

        for staff in staff_members:

            # 4. Horario del staff ese día -----------------------------------
            schedules = schedules_by_staff.get(staff.id, [])
            if not schedules:
                continue  # El staff no trabaja ese día

            # 5. Turnos ya reservados ----------------------------------------
            booked = booked_by_staff.get(staff.id, [])

            # 6. Bloqueos de agenda (StaffBlock) ------------------------------
            blocks = blocks_by_staff.get(staff.id, [])

            # 7. Cálculo de slots (granularidad 15 min) -----------------------
            for sched in schedules:
                # Forzamos que los datetimes generados de combine sean UTC aware
                current = datetime.combine(search_date, sched.start_time).replace(tzinfo=timezone.utc)
                end     = datetime.combine(search_date, sched.end_time).replace(tzinfo=timezone.utc)

                while current + duration <= end:
                    slot_end = current + duration

                    # Verificar conflicto con turnos
                    blocked_by_appt = any(
                        not (slot_end <= appt.starts_at or current >= appt.ends_at)
                        for appt in booked
                    )

                    # Verificar conflicto con bloqueos de agenda
                    overlapping_block = next(
                        (b for b in blocks if b.overlaps_with(current, slot_end)),
                        None
                    )
                    
                    # Forcing Function: min_booking_notice
                    too_soon = current < min_bookable_time

                    status = "available"
                    reason = None

                    if blocked_by_appt:
                        status = "booked"
                    elif overlapping_block:
                        status = "blocked"
                        reason = "No disponible" if hide_private_reasons else overlapping_block.note
                    elif too_soon:
                        status = "blocked"
                        reason = f"Requiere {notice_hours}h de antelación"

                    all_slots.append({
                        "staff_id":   staff.public_id,
                        "staff_name": staff.display_name,
                        "starts_at":  current.isoformat(),
                        "ends_at":    slot_end.isoformat(),
                        "start_time": current.time().isoformat(timespec="seconds"),
                        "end_time":   slot_end.time().isoformat(timespec="seconds"),
                        "status":     status,
                        "reason":     reason
                    })

                    current += timedelta(minutes=15)

        # 8. Caché por 5 minutos --------------------------------------------
        # Apply strict gap filtering unless force_all is True
        if not force_all:
            # Build mapping per staff for quick adjacency checks
            slots_by_staff = {}
            for slot in all_slots:
                slots_by_staff.setdefault(slot["staff_id"], []).append(slot)
            filtered_slots = []
            for staff_id, staff_slots in slots_by_staff.items():
                # Index by start time for fast lookup
                start_index = {s["starts_at"]: s for s in staff_slots}
                end_index = {s["ends_at"]: s for s in staff_slots}
                for slot in staff_slots:
                    # Keep if at day bounds or adjacent to another slot
                    is_first = slot["starts_at"] == start_index[slot["starts_at"]]["starts_at"] and slot["starts_at"] == min(start_index.keys())
                    is_last = slot["ends_at"] == max(end_index.keys())
                    adjacent = slot["ends_at"] in start_index or slot["starts_at"] in end_index
                    if is_first or is_last or adjacent:
                        filtered_slots.append(slot)
            all_slots = filtered_slots
        await self.redis.setex(cache_key, 300, json.dumps(all_slots))
        return all_slots
