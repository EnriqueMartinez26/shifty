from datetime import datetime, timedelta, timezone

from fastapi import Depends
from core.router import CanonicalAPIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.appointments.model import Appointment, AppointmentStatus
from modules.auth.dependencies import get_current_user
from modules.dashboard.schemas import (
    DashboardStatSummary,
    DashboardSummaryResponse,
    UpcomingAppointmentItem,
)
from modules.payments.model import Payment, PaymentStatus
from modules.services.model import Service
from modules.staff.model import Schedule, Staff
from modules.users.model import User, UserRole

router = CanonicalAPIRouter(prefix="/dashboard", tags=["Dashboard"])

# Un pago cuenta como ingreso solo si esta acreditado (Mercado Pago aprobado o
# cobro manual confirmado). Mismo criterio que modules/reports/service.py.
_ACCREDITED_PAYMENT_STATUSES = [
    PaymentStatus.APPROVED.value,
    PaymentStatus.MANUAL_CONFIRMED.value,
]


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    """Devuelve métricas resumidas y próximos turnos para el dashboard."""
    now = datetime.now(timezone.utc)
    start_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    end_today = start_today + timedelta(days=1)

    week_start = start_today - timedelta(days=start_today.weekday())
    week_start = week_start.replace(tzinfo=timezone.utc)
    week_end = week_start + timedelta(days=7)

    last_30_days = now - timedelta(days=30)

    appointments_today_q = await db.execute(
        select(func.count(Appointment.id)).where(
            Appointment.starts_at >= start_today.replace(tzinfo=None),
            Appointment.starts_at < end_today.replace(tzinfo=None),
            Appointment.status != AppointmentStatus.CANCELLED.value,
        )
    )
    appointments_today = int(appointments_today_q.scalar() or 0)

    pending_q = await db.execute(
        select(func.count(Appointment.id)).where(
            Appointment.status == AppointmentStatus.PENDING.value
        )
    )
    pending_confirmations = int(pending_q.scalar() or 0)

    # 1. Total minutos reservados hoy
    booked_mins_q = await db.execute(
        select(func.coalesce(func.sum(Service.duration_minutes), 0))
        .select_from(Appointment)
        .join(Service, Appointment.service_id == Service.id)
        .where(
            Appointment.starts_at >= start_today.replace(tzinfo=None),
            Appointment.starts_at < end_today.replace(tzinfo=None),
            Appointment.status != AppointmentStatus.CANCELLED.value,
        )
    )
    booked_mins = float(booked_mins_q.scalar() or 0)

    # 2. Total minutos disponibles (según Schedules de staff activo)
    # Calculamos la duración en Python para que sea agnóstico a la base de datos (PostgreSQL vs SQLite)
    day_of_week = start_today.weekday()
    schedules_q = await db.execute(
        select(Schedule).where(Schedule.day_of_week == day_of_week)
    )
    total_avail_mins = 0.0
    for (sch,) in schedules_q:
        if sch.start_time and sch.end_time:
            # convert to timedelta using datetime.combine
            t1 = datetime.combine(datetime.today(), sch.start_time)
            t2 = datetime.combine(datetime.today(), sch.end_time)
            if t2 > t1:
                total_avail_mins += (t2 - t1).total_seconds() / 60.0

    occupancy_rate = 0.0
    if total_avail_mins > 0:
        occupancy_rate = round((booked_mins / total_avail_mins) * 100, 2)

    new_clients_q = await db.execute(
        select(func.count(User.id)).where(
            User.role == UserRole.CLIENT.value,
            User.created_at >= last_30_days.replace(tzinfo=None),
        )
    )
    new_clients_last_30d = int(new_clients_q.scalar() or 0)

    async def _accredited_revenue(desde: datetime, hasta: datetime) -> float:
        """Ingreso = plata acreditada de turnos cuyo inicio cae en el rango.

        Antes sumaba Service.price (precio de lista actual) de turnos CONFIRMED/
        COMPLETED, lo que contaba turnos sin cobrar y a precio equivocado. Ahora
        es consistente con el reporte de ingresos: solo pagos acreditados.
        """
        query = await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .select_from(Payment)
            .join(Appointment, Payment.appointment_id == Appointment.id)
            .where(
                Appointment.starts_at >= desde.replace(tzinfo=None),
                Appointment.starts_at < hasta.replace(tzinfo=None),
                Payment.status.in_(_ACCREDITED_PAYMENT_STATUSES),
            )
        )
        return float(query.scalar() or 0)

    weekly_revenue = await _accredited_revenue(week_start, week_end)

    # 3. Tendencia (Semana pasada)
    last_week_start = week_start - timedelta(days=7)
    last_week_end = week_start
    last_week_revenue = await _accredited_revenue(last_week_start, last_week_end)

    revenue_trend = 0.0
    if last_week_revenue > 0:
        revenue_trend = round(
            ((weekly_revenue - last_week_revenue) / last_week_revenue) * 100, 2
        )
    elif weekly_revenue > 0:
        revenue_trend = 100.0

    avg_duration_q = await db.execute(
        select(func.coalesce(func.avg(Service.duration_minutes), 0))
        .select_from(Appointment)
        .join(Service, Appointment.service_id == Service.id)
        .where(
            Appointment.starts_at >= week_start.replace(tzinfo=None),
            Appointment.starts_at < week_end.replace(tzinfo=None),
            Appointment.status != AppointmentStatus.CANCELLED.value,
        )
    )
    average_appointment_minutes = int(round(float(avg_duration_q.scalar() or 0)))

    upcoming_q = await db.execute(
        select(Appointment, Service, Staff, User)
        .join(Service, Appointment.service_id == Service.id)
        .join(Staff, Appointment.staff_id == Staff.id)
        .join(User, Appointment.client_id == User.id)
        .where(
            Appointment.starts_at >= now.replace(tzinfo=None),
            Appointment.status.in_(
                [
                    AppointmentStatus.PENDING.value,
                    AppointmentStatus.CONFIRMED.value,
                ]
            ),
        )
        .order_by(Appointment.starts_at.asc())
        .limit(5)
    )

    upcoming_items: list[UpcomingAppointmentItem] = []
    for appointment, service, staff, client in upcoming_q.all():
        upcoming_items.append(
            UpcomingAppointmentItem(
                public_id=appointment.public_id,
                starts_at=appointment.starts_at,
                status=appointment.status,
                service_name=service.name,
                staff_name=staff.display_name,
                client_name=client.full_name or client.email,
            )
        )

    return DashboardSummaryResponse(
        stats=DashboardStatSummary(
            appointments_today=appointments_today,
            pending_confirmations=pending_confirmations,
            occupancy_rate=occupancy_rate,
            new_clients_last_30d=new_clients_last_30d,
            weekly_revenue=weekly_revenue,
            revenue_trend=revenue_trend,
            average_appointment_minutes=average_appointment_minutes,
        ),
        upcoming_appointments=upcoming_items,
    )
