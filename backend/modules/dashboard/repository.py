"""DashboardRepository — consultas del panel.

Acceso puro a datos (CLAUDE.md §2): sin reglas de negocio ni commits. Cada
consulta lleva el predicado ``store_id`` de la tienda del request aunque RLS
ya filtre (defensa en profundidad, B5-01), tambien para el superadmin (B5-02).
Los instantes se reciben aware en UTC y se comparan aware: ``starts_at`` y
``created_at`` son ``timestamptz``, y asyncpg codifica un naive como hora local
DEL HOST (AUD2-B5-07). Es el mismo criterio que ``modules/reports`` (regla 24).

Cuatro sentencias por panel (F3-04, R2-03; antes nueve, mas dos de
``selectin`` por cargar ``Staff`` como entidad en ``upcoming``). Las metricas
que leen la misma ventana de turnos viajan juntas con agregados condicionales
(``FILTER``, que Postgres y SQLite >= 3.30 soportan): cada una conserva su
propio predicado, solo dejan de ir y volver por separado.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import NamedTuple

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import Payment
from modules.reports.service import ACCREDITED_PAYMENT_STATUSES
from modules.services.model import Service
from modules.staff.model import Schedule, Staff
from modules.users.model import User, UserRole


class DayCounters(NamedTuple):
    """Contadores de "hoy", de lo pendiente y de clientes nuevos."""

    appointments_today: int
    booked_minutes_today: float
    pending_from_now: int
    new_clients: int


class WeekTotals(NamedTuple):
    """Ingreso de la semana y de la anterior, y duracion promedio de la semana."""

    revenue: float
    previous_revenue: float
    average_minutes: float


class UpcomingRow(NamedTuple):
    """Columnas de un proximo turno: ninguna entidad, ninguna relacion."""

    public_id: str
    starts_at: datetime
    status: str
    service_name: str
    staff_name: str
    client_first_name: str | None
    client_last_name: str | None
    client_email: str


def _store_scope(
    store_id: str, column: InstrumentedAttribute[str]
) -> list[ColumnElement[bool]]:
    """Predicado ``store_id`` para desempacar en el ``where`` de cada query.

    Defensa en profundidad sobre RLS (CLAUDE.md §2): toda consulta del panel
    lleva la tienda del request aunque la politica de Postgres falle, tambien
    para el superadmin, cuya sesion abre RLS (B5-02; ver
    core.roles.store_scope_for).
    """
    return [column == store_id]


def _starts_between(desde: datetime, hasta: datetime) -> list[ColumnElement[bool]]:
    return [
        Appointment.starts_at >= desde,
        Appointment.starts_at < hasta,
    ]


def _not_cancelled() -> ColumnElement[bool]:
    return Appointment.status != AppointmentStatus.CANCELLED.value


class DashboardRepository:
    def __init__(self, db: AsyncSession, store_id: str) -> None:
        self.db = db
        self.store_id = store_id

    def _appointment_scope(self) -> list[ColumnElement[bool]]:
        return _store_scope(self.store_id, Appointment.store_id)

    async def day_counters(
        self,
        today_from: datetime,
        today_to: datetime,
        now: datetime,
        new_clients_since: datetime,
    ) -> DayCounters:
        """Turnos y minutos de hoy, pendientes desde ``now`` y clientes nuevos.

        - Hoy: turnos no cancelados cuyo inicio cae en ``[today_from,
          today_to)`` y sus minutos segun el snapshot del turno (AUD2-B5-10:
          sumar ``Service.duration_minutes`` recalculaba hacia atras la
          ocupacion al alargar un servicio).
        - Pendientes: los que empiezan de ``now`` en adelante (AUD2-B5-11: sin
          esa cota el contador crecia para siempre).
        - Clientes nuevos: subconsulta escalar sobre ``users`` con su propio
          ``store_id``; viaja en la misma sentencia.

        El ``where`` externo es la union de las dos ventanas de turnos: del
        comienzo del dia local (o ``now``, el menor) en adelante.
        """
        today = and_(*_starts_between(today_from, today_to), _not_cancelled())
        pending = and_(
            Appointment.starts_at >= now,
            Appointment.status == AppointmentStatus.PENDING.value,
        )
        new_clients = (
            select(func.count(User.id))
            .where(
                User.role == UserRole.CLIENT.value,
                User.created_at >= new_clients_since,
                *_store_scope(self.store_id, User.store_id),
            )
            .scalar_subquery()
        )
        result = await self.db.execute(
            select(
                func.count(Appointment.id).filter(today),
                func.coalesce(func.sum(Appointment.duration_minutes).filter(today), 0),
                func.count(Appointment.id).filter(pending),
                new_clients,
            ).where(
                Appointment.starts_at >= min(today_from, now),
                *self._appointment_scope(),
            )
        )
        today_count, booked, pending_count, new_count = result.one()
        return DayCounters(
            appointments_today=int(today_count or 0),
            booked_minutes_today=float(booked or 0),
            pending_from_now=int(pending_count or 0),
            new_clients=int(new_count or 0),
        )

    async def week_totals(
        self, week_from: datetime, week_to: datetime, previous_from: datetime
    ) -> WeekTotals:
        """Ingreso de ``[week_from, week_to)`` y de ``[previous_from,
        week_from)``, y duracion promedio de la semana, en una sentencia.

        Ingreso = plata acreditada de turnos cuyo inicio cae en el rango, de
        cualquier estado, igual que el reporte de ingresos. El ``LEFT JOIN`` a
        ``payments`` no duplica turnos: ``uq_payments_store_appointment``
        garantiza a lo sumo un pago por turno y por tienda, asi que el promedio
        sigue siendo por turno. El pago lleva su propio ``store_id``
        (AUD2-B5-16). La duracion sale del snapshot del turno (AUD2-B5-10) y
        excluye los cancelados.
        """
        week = and_(*_starts_between(week_from, week_to))
        previous = and_(*_starts_between(previous_from, week_from))
        result = await self.db.execute(
            select(
                func.coalesce(func.sum(Payment.amount).filter(week), 0),
                func.coalesce(func.sum(Payment.amount).filter(previous), 0),
                func.coalesce(
                    func.avg(Appointment.duration_minutes).filter(
                        and_(week, _not_cancelled())
                    ),
                    0,
                ),
            )
            .select_from(Appointment)
            .outerjoin(
                Payment,
                and_(
                    Payment.appointment_id == Appointment.id,
                    Payment.status.in_(ACCREDITED_PAYMENT_STATUSES),
                    *_store_scope(self.store_id, Payment.store_id),
                ),
            )
            .where(
                *_starts_between(previous_from, week_to),
                *self._appointment_scope(),
            )
        )
        revenue, previous_revenue, average = result.one()
        return WeekTotals(
            revenue=float(revenue or 0),
            previous_revenue=float(previous_revenue or 0),
            average_minutes=float(average or 0),
        )

    async def schedules_for_weekday(self, day_of_week: int) -> list[tuple[time, time]]:
        """Franjas ``(inicio, fin)`` del dia de la semana del staff ACTIVO.

        B5-11: sin el join, los horarios de un profesional dado de baja seguian
        sumando minutos disponibles y diluian ``occupancy_rate``. Mismo criterio
        que el reporte por profesional (``Staff.is_active``). Solo columnas: la
        capacidad no necesita la entidad.
        """
        result = await self.db.execute(
            select(Schedule.start_time, Schedule.end_time)
            .join(Staff, Schedule.staff_id == Staff.id)
            .where(
                Schedule.day_of_week == day_of_week,
                Staff.is_active.is_(True),
                *_store_scope(self.store_id, Schedule.store_id),
            )
        )
        return [(start, end) for start, end in result.all()]

    async def upcoming(self, since: datetime, limit: int) -> list[UpcomingRow]:
        """Proximos turnos pendientes o confirmados, del mas cercano al mas lejano.

        Por columnas: cargar ``Staff`` como entidad disparaba sus relaciones
        (dos sentencias mas) para leer solo ``display_name``.
        """
        result = await self.db.execute(
            select(
                Appointment.id,
                Appointment.starts_at,
                Appointment.status,
                Service.name,
                Staff.display_name,
                User.first_name,
                User.last_name,
                User.email,
            )
            .join(Service, Appointment.service_id == Service.id)
            .join(Staff, Appointment.staff_id == Staff.id)
            .join(User, Appointment.client_id == User.id)
            .where(
                Appointment.starts_at >= since,
                Appointment.status.in_(
                    [
                        AppointmentStatus.PENDING.value,
                        AppointmentStatus.CONFIRMED.value,
                    ]
                ),
                *self._appointment_scope(),
            )
            .order_by(Appointment.starts_at.asc())
            .limit(limit)
        )
        return [UpcomingRow(*row) for row in result.all()]
