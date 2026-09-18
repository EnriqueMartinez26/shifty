"""DashboardService — compone las metricas del panel sobre el repositorio.

Orquestacion pura (CLAUDE.md §2): decide los rangos y las formulas; las
consultas son de ``DashboardRepository``. Es solo lectura, asi que no abre ni
commitea transacciones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from core.utils import local_day_start, now_utc, today_local
from modules.dashboard.repository import DashboardRepository, UpcomingRow
from modules.dashboard.schemas import (
    DashboardStatSummary,
    DashboardSummaryResponse,
    UpcomingAppointmentItem,
)
from modules.staff.model import Schedule

UPCOMING_LIMIT = 5


@dataclass(frozen=True)
class _Window:
    """Rango ``[desde, hasta)`` en UTC aware."""

    desde: datetime
    hasta: datetime


def _local_days(first_day: date, days: int) -> _Window:
    # "Hoy" y "la semana" son dias del calendario argentino convertidos a UTC
    # (regla 24), no el dia UTC: un turno de las 22:30 hora local se persiste
    # a la 01:30Z del dia siguiente y tiene que contar en el dia local.
    return _Window(
        local_day_start(first_day), local_day_start(first_day + timedelta(days=days))
    )


def _available_minutes(schedules: list[Schedule]) -> float:
    # Calculamos la duración en Python para que sea agnóstico a la base de
    # datos (PostgreSQL vs SQLite).
    total = 0.0
    for sch in schedules:
        if sch.start_time and sch.end_time:
            t1 = datetime.combine(datetime.today(), sch.start_time)
            t2 = datetime.combine(datetime.today(), sch.end_time)
            if t2 > t1:
                total += (t2 - t1).total_seconds() / 60.0
    return total


def _occupancy_rate(booked_mins: float, available_mins: float) -> float:
    if available_mins > 0:
        return round((booked_mins / available_mins) * 100, 2)
    return 0.0


def _revenue_trend(current: float, previous: float) -> float:
    """Variacion porcentual del ingreso contra la semana anterior."""
    if previous > 0:
        return round(((current - previous) / previous) * 100, 2)
    if current > 0:
        return 100.0
    return 0.0


def _upcoming_item(row: UpcomingRow) -> UpcomingAppointmentItem:
    appointment, service, staff, client = row
    return UpcomingAppointmentItem(
        public_id=appointment.public_id,
        starts_at=appointment.starts_at,
        status=appointment.status,
        service_name=service.name,
        staff_name=staff.display_name,
        client_name=client.full_name or client.email,
    )


class DashboardService:
    def __init__(self, repository: DashboardRepository) -> None:
        self.repository = repository

    async def _occupancy_today(self, today: date, window: _Window) -> float:
        """Minutos reservados hoy sobre minutos de agenda del dia de la semana."""
        booked = await self.repository.booked_minutes_between(
            window.desde, window.hasta
        )
        schedules = await self.repository.schedules_for_weekday(today.weekday())
        return _occupancy_rate(booked, _available_minutes(schedules))

    async def get_summary(self) -> DashboardSummaryResponse:
        """Devuelve métricas resumidas y próximos turnos para el dashboard."""
        repo = self.repository
        now = now_utc()
        today = today_local()
        monday = today - timedelta(days=today.weekday())
        today_window = _local_days(today, 1)
        week = _local_days(monday, 7)
        last_week = _Window(local_day_start(monday - timedelta(days=7)), week.desde)

        weekly_revenue = await repo.accredited_revenue_between(week.desde, week.hasta)
        last_week_revenue = await repo.accredited_revenue_between(
            last_week.desde, last_week.hasta
        )
        average_minutes = await repo.average_duration_between(week.desde, week.hasta)

        stats = DashboardStatSummary(
            appointments_today=await repo.count_active_between(
                today_window.desde, today_window.hasta
            ),
            pending_confirmations=await repo.count_pending(),
            occupancy_rate=await self._occupancy_today(today, today_window),
            new_clients_last_30d=await repo.count_new_clients_since(
                now - timedelta(days=30)
            ),
            weekly_revenue=weekly_revenue,
            revenue_trend=_revenue_trend(weekly_revenue, last_week_revenue),
            average_appointment_minutes=int(round(average_minutes)),
        )
        upcoming = await repo.upcoming(now, UPCOMING_LIMIT)
        return DashboardSummaryResponse(
            stats=stats,
            upcoming_appointments=[_upcoming_item(row) for row in upcoming],
        )
