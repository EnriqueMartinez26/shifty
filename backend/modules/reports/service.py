from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment, AppointmentStatus
from modules.reports.schemas import (
    ProfessionalReportItem,
    ProfessionalReportsResponse,
    ReportAppointmentItem,
    ReportSummaryResponse,
    ReportSummaryStats,
)
from modules.services.model import Service
from modules.staff.model import Schedule, Staff, StaffBlock


class ReportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _resolve_date_range(self, from_date: date | None, to_date: date | None) -> tuple[date, date]:
        today = datetime.now(timezone.utc).date()
        resolved_to = to_date or today
        resolved_from = from_date or (resolved_to - timedelta(days=30))

        if resolved_from > resolved_to:
            raise ValueError("from_date no puede ser mayor a to_date")

        return resolved_from, resolved_to

    def _range_bounds(self, from_date: date, to_date: date) -> tuple[datetime, datetime]:
        start_dt = datetime.combine(from_date, time.min)
        end_dt = datetime.combine(to_date + timedelta(days=1), time.min)
        return start_dt, end_dt

    async def _fetch_rows(
        self,
        *,
        from_date: date,
        to_date: date,
        staff_id: str | None = None,
    ) -> list[tuple[Appointment, Service, Staff]]:
        start_dt, end_dt = self._range_bounds(from_date, to_date)
        query = (
            select(Appointment, Service, Staff)
            .join(Service, Appointment.service_id == Service.id)
            .join(Staff, Appointment.staff_id == Staff.id)
            .where(Appointment.starts_at >= start_dt, Appointment.starts_at < end_dt)
            .order_by(Appointment.starts_at.asc())
        )
        if staff_id:
            query = query.where(Appointment.staff_id == staff_id)
        result = await self.db.execute(query)
        return list(result.all())

    async def get_summary(
        self,
        from_date: date | None,
        to_date: date | None,
        *,
        staff_id: str | None = None,
    ) -> ReportSummaryResponse:
        resolved_from, resolved_to = self._resolve_date_range(from_date, to_date)
        rows = await self._fetch_rows(from_date=resolved_from, to_date=resolved_to, staff_id=staff_id)

        items: list[ReportAppointmentItem] = []
        total_revenue = 0.0
        completed = 0
        cancelled = 0
        pending = 0
        confirmed = 0

        for appointment, service, staff in rows:
            status = appointment.status
            price = float(service.price)
            status_upper = status.upper() if status else ""

            if status_upper == "COMPLETED":
                completed += 1
                total_revenue += price
            elif status_upper == "CANCELLED":
                cancelled += 1
            elif status_upper in {"PENDING", "PENDING_PAYMENT"}:
                pending += 1
            elif status_upper == "CONFIRMED":
                confirmed += 1
                total_revenue += price

            items.append(
                ReportAppointmentItem(
                    public_id=appointment.public_id,
                    starts_at=appointment.starts_at,
                    ends_at=appointment.ends_at,
                    status=status,
                    service_name=service.name,
                    staff_name=staff.display_name,
                    client_name=appointment.client_name,
                    service_price=price,
                )
            )

        total = len(items)
        average_ticket = (total_revenue / total) if total else 0.0

        stats = ReportSummaryStats(
            total_appointments=total,
            completed_appointments=completed,
            cancelled_appointments=cancelled,
            pending_appointments=pending,
            confirmed_appointments=confirmed,
            total_revenue=round(total_revenue, 2),
            average_ticket=round(average_ticket, 2),
        )

        return ReportSummaryResponse(
            from_date=resolved_from,
            to_date=resolved_to,
            stats=stats,
            appointments=items,
        )

    async def get_professionals(
        self,
        from_date: date | None,
        to_date: date | None,
        *,
        only_staff_id: str | None = None,
    ) -> ProfessionalReportsResponse:
        resolved_from, resolved_to = self._resolve_date_range(from_date, to_date)
        start_dt, end_dt = self._range_bounds(resolved_from, resolved_to)

        staff_query = select(Staff).where(Staff.is_active.is_(True))
        if only_staff_id:
            staff_query = staff_query.where(Staff.id == only_staff_id)
        staff_result = await self.db.execute(staff_query.order_by(Staff.display_name.asc()))
        staff_members = list(staff_result.scalars().all())
        staff_ids = [staff.id for staff in staff_members]
        if not staff_ids:
            return ProfessionalReportsResponse(from_date=resolved_from, to_date=resolved_to, professionals=[])

        schedules_result = await self.db.execute(select(Schedule).where(Schedule.staff_id.in_(staff_ids)))
        blocks_result = await self.db.execute(
            select(StaffBlock).where(
                StaffBlock.staff_id.in_(staff_ids),
                StaffBlock.is_active.is_(True),
                StaffBlock.starts_at < end_dt,
                StaffBlock.ends_at > start_dt,
            )
        )
        rows = await self._fetch_rows(from_date=resolved_from, to_date=resolved_to, staff_id=only_staff_id)

        schedules_by_staff: dict[str, list[Schedule]] = defaultdict(list)
        for schedule in schedules_result.scalars().all():
            schedules_by_staff[schedule.staff_id].append(schedule)

        blocks_by_staff: dict[str, list[StaffBlock]] = defaultdict(list)
        for block in blocks_result.scalars().all():
            blocks_by_staff[block.staff_id].append(block)

        appointments_by_staff: dict[str, list[tuple[Appointment, Service, Staff]]] = defaultdict(list)
        for row in rows:
            appointment, _service, staff = row
            appointments_by_staff[staff.id].append(row)

        items: list[ProfessionalReportItem] = []
        total_days = (resolved_to - resolved_from).days + 1

        for staff in staff_members:
            available_minutes = 0
            for schedule in schedules_by_staff.get(staff.id, []):
                daily_minutes = int(
                    (datetime.combine(date.min, schedule.end_time) - datetime.combine(date.min, schedule.start_time)).total_seconds()
                    // 60
                )
                matching_days = sum(
                    1
                    for offset in range(total_days)
                    if (resolved_from + timedelta(days=offset)).weekday() == schedule.day_of_week
                )
                available_minutes += daily_minutes * matching_days

            blocked_minutes = 0
            for block in blocks_by_staff.get(staff.id, []):
                clipped_start = max(block.starts_at.replace(tzinfo=None), start_dt)
                clipped_end = min(block.ends_at.replace(tzinfo=None), end_dt)
                if clipped_end > clipped_start:
                    blocked_minutes += int((clipped_end - clipped_start).total_seconds() // 60)

            total_appointments = 0
            completed = 0
            confirmed = 0
            absent = 0
            cancelled = 0
            used_minutes = 0
            revenue = 0.0

            for appointment, service, _ in appointments_by_staff.get(staff.id, []):
                total_appointments += 1
                if appointment.status not in {AppointmentStatus.CANCELLED.value, AppointmentStatus.EXPIRED.value}:
                    used_minutes += int(appointment.duration_minutes)
                if appointment.status == AppointmentStatus.COMPLETED.value:
                    completed += 1
                    revenue += float(service.price)
                elif appointment.status == AppointmentStatus.CONFIRMED.value:
                    confirmed += 1
                    revenue += float(service.price)
                elif appointment.status == AppointmentStatus.ABSENT.value:
                    absent += 1
                elif appointment.status == AppointmentStatus.CANCELLED.value:
                    cancelled += 1

            effective_minutes = max(available_minutes - blocked_minutes, 0)
            occupancy_rate = round((used_minutes / effective_minutes) * 100, 2) if effective_minutes else 0.0
            items.append(
                ProfessionalReportItem(
                    staff_id=staff.public_id,
                    staff_name=staff.display_name,
                    appointments=total_appointments,
                    completed_appointments=completed,
                    confirmed_appointments=confirmed,
                    absent_appointments=absent,
                    cancelled_appointments=cancelled,
                    used_minutes=used_minutes,
                    used_hours=round(used_minutes / 60, 2),
                    available_minutes=available_minutes,
                    available_hours=round(available_minutes / 60, 2),
                    blocked_minutes=blocked_minutes,
                    blocked_hours=round(blocked_minutes / 60, 2),
                    occupancy_rate=occupancy_rate,
                    revenue=round(revenue, 2),
                )
            )

        return ProfessionalReportsResponse(
            from_date=resolved_from,
            to_date=resolved_to,
            professionals=items,
        )
