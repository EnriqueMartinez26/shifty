"""DashboardService — compone las metricas del panel sobre el repositorio.

Orquestacion pura (CLAUDE.md §2): decide los rangos y las formulas; las
consultas son de ``DashboardRepository``. Es solo lectura, asi que no abre ni
commitea transacciones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from core.utils import local_day_start, now_utc, today_local
from modules.dashboard.repository import DashboardRepository, UpcomingRow
from modules.dashboard.schemas import (
    DashboardStatSummary,
    DashboardSummaryResponse,
    UpcomingAppointmentItem,
)

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


def _available_minutes(schedules: list[tuple[time, time]]) -> float:
    # Calculamos la duración en Python para que sea agnóstico a la base de
    # datos (PostgreSQL vs SQLite).
    total = 0.0
    for start_time, end_time in schedules:
        if start_time and end_time:
            t1 = datetime.combine(datetime.today(), start_time)
            t2 = datetime.combine(datetime.today(), end_time)
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
    # Mismo nombre que ``User.full_name`` (nombre y apellido sin blancos
    # sobrantes) y, si no hay, el email.
    full_name = " ".join(
        part.strip()
        for part in (row.client_first_name, row.client_last_name)
        if part and part.strip()
    )
    return UpcomingAppointmentItem(
        public_id=row.public_id,
        starts_at=row.starts_at,
        status=row.status,
        service_name=row.service_name,
        staff_name=row.staff_name,
        client_name=full_name or row.client_email,
    )


class DashboardService:
    def __init__(self, repository: DashboardRepository) -> None:
        self.repository = repository

    async def get_summary(self) -> DashboardSummaryResponse:
        """Devuelve métricas resumidas y próximos turnos para el dashboard.

        Cuatro sentencias (F3-04): "hoy" + pendientes + clientes nuevos, la
        semana y la anterior, los horarios de hoy y los proximos turnos.
        """
        repo = self.repository
        now = now_utc()
        today = today_local()
        monday = today - timedelta(days=today.weekday())
        today_window = _local_days(today, 1)
        week = _local_days(monday, 7)
        last_week_start = local_day_start(monday - timedelta(days=7))

        day = await repo.day_counters(
            today_window.desde,
            today_window.hasta,
            now,
            new_clients_since=now - timedelta(days=30),
        )
        week_totals = await repo.week_totals(week.desde, week.hasta, last_week_start)
        schedules = await repo.schedules_for_weekday(today.weekday())

        stats = DashboardStatSummary(
            appointments_today=day.appointments_today,
            pending_confirmations=day.pending_from_now,
            # Minutos reservados hoy sobre la agenda del dia del staff activo.
            occupancy_rate=_occupancy_rate(
                day.booked_minutes_today, _available_minutes(schedules)
            ),
            new_clients_last_30d=day.new_clients,
            weekly_revenue=week_totals.revenue,
            revenue_trend=_revenue_trend(
                week_totals.revenue, week_totals.previous_revenue
            ),
            average_appointment_minutes=int(round(week_totals.average_minutes)),
        )
        upcoming = await repo.upcoming(now, UPCOMING_LIMIT)
        return DashboardSummaryResponse(
            stats=stats,
            upcoming_appointments=[_upcoming_item(row) for row in upcoming],
        )
