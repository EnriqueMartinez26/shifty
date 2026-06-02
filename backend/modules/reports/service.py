from datetime import date, datetime, time, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment, AppointmentStatus
from modules.services.model import Service
from modules.staff.model import Staff
from modules.users.model import User
from modules.reports.schemas import (
    ReportAppointmentItem,
    ReportSummaryResponse,
    ReportSummaryStats,
)


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

    async def get_summary(self, from_date: date | None, to_date: date | None) -> ReportSummaryResponse:
        resolved_from, resolved_to = self._resolve_date_range(from_date, to_date)

        start_dt = datetime.combine(resolved_from, time.min)
        end_dt = datetime.combine(resolved_to + timedelta(days=1), time.min)

        query = (
            select(Appointment, Service, Staff)
            .join(Service, Appointment.service_id == Service.id)
            .join(Staff, Appointment.staff_id == Staff.id)
            .where(Appointment.starts_at >= start_dt, Appointment.starts_at < end_dt)
            .order_by(Appointment.starts_at.asc())
        )

        result = await self.db.execute(query)
        rows = list(result.all())

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
            elif status_upper == "PENDING":
                pending += 1
            elif status_upper == "CONFIRMED":
                confirmed += 1
                total_revenue += price

            ends_at = appointment.starts_at + timedelta(minutes=appointment.duration_minutes)
            items.append(
                ReportAppointmentItem(
                    public_id=appointment.public_id,
                    starts_at=appointment.starts_at,
                    ends_at=ends_at,
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
