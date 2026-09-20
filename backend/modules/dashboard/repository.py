"""DashboardRepository — consultas del panel, una por metrica.

Acceso puro a datos (CLAUDE.md §2): sin reglas de negocio ni commits. Cada
consulta lleva el predicado ``store_id`` de la tienda del request aunque RLS
ya filtre (defensa en profundidad, B5-01), tambien para el superadmin (B5-02).
Los instantes se reciben aware en UTC y se comparan aware: ``starts_at`` y
``created_at`` son ``timestamptz``, y asyncpg codifica un naive como hora local
DEL HOST (AUD2-B5-07). Es el mismo criterio que ``modules/reports`` (regla 24).
"""

from __future__ import annotations

from datetime import datetime
from typing import TypeAlias

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import Payment
from modules.reports.service import ACCREDITED_PAYMENT_STATUSES
from modules.services.model import Service
from modules.staff.model import Schedule, Staff
from modules.users.model import User, UserRole

UpcomingRow: TypeAlias = tuple[Appointment, Service, Staff, User]


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


class DashboardRepository:
    def __init__(self, db: AsyncSession, store_id: str) -> None:
        self.db = db
        self.store_id = store_id

    def _appointment_scope(self) -> list[ColumnElement[bool]]:
        return _store_scope(self.store_id, Appointment.store_id)

    async def count_active_between(self, desde: datetime, hasta: datetime) -> int:
        """Turnos no cancelados cuyo inicio cae en ``[desde, hasta)``."""
        result = await self.db.execute(
            select(func.count(Appointment.id)).where(
                *_starts_between(desde, hasta),
                Appointment.status != AppointmentStatus.CANCELLED.value,
                *self._appointment_scope(),
            )
        )
        return int(result.scalar() or 0)

    async def count_pending(self, desde: datetime) -> int:
        """Turnos pendientes que empiezan de ``desde`` en adelante.

        AUD2-B5-11: antes contaba TODOS los pendientes de la tienda, sin cota.
        Un pendiente cuya fecha ya paso no cambia de estado solo (el grafo lo
        lleva a absent/completed por accion del staff), asi que el contador era
        monotono creciente: a los seis meses mostraba "137 confirmaciones
        pendientes" donde habia dos reales y dejaba de disparar accion. El
        horizonte es el mismo que el de ``upcoming``.
        """
        result = await self.db.execute(
            select(func.count(Appointment.id)).where(
                Appointment.starts_at >= desde,
                Appointment.status == AppointmentStatus.PENDING.value,
                *self._appointment_scope(),
            )
        )
        return int(result.scalar() or 0)

    async def booked_minutes_between(self, desde: datetime, hasta: datetime) -> float:
        """Minutos reservados (no cancelados) en el rango, segun el turno.

        AUD2-B5-10: sumaba ``Service.duration_minutes``, la duracion de lista
        de HOY, asi que alargar un servicio recalculaba hacia atras la
        ocupacion de una agenda que no cambio y la separaba del reporte por
        profesional, que usa el snapshot. Misma razon por la que el turno
        congela ``price_amount``.
        """
        result = await self.db.execute(
            select(func.coalesce(func.sum(Appointment.duration_minutes), 0))
            .select_from(Appointment)
            .where(
                *_starts_between(desde, hasta),
                Appointment.status != AppointmentStatus.CANCELLED.value,
                *self._appointment_scope(),
            )
        )
        return float(result.scalar() or 0)

    async def schedules_for_weekday(self, day_of_week: int) -> list[Schedule]:
        """Horarios del dia de la semana del staff ACTIVO (capacidad de hoy).

        B5-11: sin el join, los horarios de un profesional dado de baja seguian
        sumando minutos disponibles y diluian ``occupancy_rate``. Mismo criterio
        que el reporte por profesional (``Staff.is_active``).
        """
        result = await self.db.execute(
            select(Schedule)
            .join(Staff, Schedule.staff_id == Staff.id)
            .where(
                Schedule.day_of_week == day_of_week,
                Staff.is_active.is_(True),
                *_store_scope(self.store_id, Schedule.store_id),
            )
        )
        return list(result.scalars().all())

    async def count_new_clients_since(self, since: datetime) -> int:
        result = await self.db.execute(
            select(func.count(User.id)).where(
                User.role == UserRole.CLIENT.value,
                User.created_at >= since,
                *_store_scope(self.store_id, User.store_id),
            )
        )
        return int(result.scalar() or 0)

    async def accredited_revenue_between(
        self, desde: datetime, hasta: datetime
    ) -> float:
        """Ingreso = plata acreditada de turnos cuyo inicio cae en el rango.

        Antes sumaba Service.price (precio de lista actual) de turnos CONFIRMED/
        COMPLETED, lo que contaba turnos sin cobrar y a precio equivocado. Ahora
        es consistente con el reporte de ingresos: solo pagos acreditados.
        """
        result = await self.db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .select_from(Payment)
            .join(Appointment, Payment.appointment_id == Appointment.id)
            .where(
                *_starts_between(desde, hasta),
                Payment.status.in_(ACCREDITED_PAYMENT_STATUSES),
                *self._appointment_scope(),
            )
        )
        return float(result.scalar() or 0)

    async def average_duration_between(self, desde: datetime, hasta: datetime) -> float:
        """Duracion promedio de los turnos no cancelados del rango.

        Sobre el snapshot del turno, por lo mismo que ``booked_minutes_between``
        (AUD2-B5-10).
        """
        result = await self.db.execute(
            select(func.coalesce(func.avg(Appointment.duration_minutes), 0))
            .select_from(Appointment)
            .where(
                *_starts_between(desde, hasta),
                Appointment.status != AppointmentStatus.CANCELLED.value,
                *self._appointment_scope(),
            )
        )
        return float(result.scalar() or 0)

    async def upcoming(self, since: datetime, limit: int) -> list[UpcomingRow]:
        """Proximos turnos pendientes o confirmados, del mas cercano al mas lejano."""
        result = await self.db.execute(
            select(Appointment, Service, Staff, User)
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
        return [
            (appointment, service, staff, client)
            for appointment, service, staff, client in result.all()
        ]
