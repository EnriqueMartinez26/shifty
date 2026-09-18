"""DashboardRepository — consultas del panel, una por metrica.

Acceso puro a datos (CLAUDE.md §2): sin reglas de negocio ni commits. Cada
consulta lleva el predicado ``store_id`` de la tienda del request aunque RLS
ya filtre (defensa en profundidad, B5-01); vacio solo para el superadmin.
Los instantes se reciben aware en UTC y se comparan naive, como antes.
"""

from __future__ import annotations

from datetime import datetime
from typing import TypeAlias

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import Payment, PaymentStatus
from modules.services.model import Service
from modules.staff.model import Schedule, Staff
from modules.users.model import User, UserRole

UpcomingRow: TypeAlias = tuple[Appointment, Service, Staff, User]

# Un pago cuenta como ingreso solo si esta acreditado (Mercado Pago aprobado o
# cobro manual confirmado). Mismo criterio que modules/reports/service.py.
_ACCREDITED_PAYMENT_STATUSES = [
    PaymentStatus.APPROVED.value,
    PaymentStatus.MANUAL_CONFIRMED.value,
]


def _store_scope(
    store_id: str | None, column: InstrumentedAttribute[str]
) -> list[ColumnElement[bool]]:
    """Predicado ``store_id`` para desempacar en el ``where`` de cada query.

    Defensa en profundidad sobre RLS (CLAUDE.md §2): toda consulta del panel
    lleva la tienda del request aunque la politica de Postgres falle. Vacio
    solo para el superadmin (ver core.roles.store_scope_for).
    """
    if store_id is None:
        return []
    return [column == store_id]


def _starts_between(desde: datetime, hasta: datetime) -> list[ColumnElement[bool]]:
    return [
        Appointment.starts_at >= desde.replace(tzinfo=None),
        Appointment.starts_at < hasta.replace(tzinfo=None),
    ]


class DashboardRepository:
    def __init__(self, db: AsyncSession, store_id: str | None) -> None:
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

    async def count_pending(self) -> int:
        result = await self.db.execute(
            select(func.count(Appointment.id)).where(
                Appointment.status == AppointmentStatus.PENDING.value,
                *self._appointment_scope(),
            )
        )
        return int(result.scalar() or 0)

    async def booked_minutes_between(self, desde: datetime, hasta: datetime) -> float:
        """Minutos de servicio reservados (no cancelados) en el rango."""
        result = await self.db.execute(
            select(func.coalesce(func.sum(Service.duration_minutes), 0))
            .select_from(Appointment)
            .join(Service, Appointment.service_id == Service.id)
            .where(
                *_starts_between(desde, hasta),
                Appointment.status != AppointmentStatus.CANCELLED.value,
                *self._appointment_scope(),
            )
        )
        return float(result.scalar() or 0)

    async def schedules_for_weekday(self, day_of_week: int) -> list[Schedule]:
        result = await self.db.execute(
            select(Schedule).where(
                Schedule.day_of_week == day_of_week,
                *_store_scope(self.store_id, Schedule.store_id),
            )
        )
        return list(result.scalars().all())

    async def count_new_clients_since(self, since: datetime) -> int:
        result = await self.db.execute(
            select(func.count(User.id)).where(
                User.role == UserRole.CLIENT.value,
                User.created_at >= since.replace(tzinfo=None),
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
                Payment.status.in_(_ACCREDITED_PAYMENT_STATUSES),
                *self._appointment_scope(),
            )
        )
        return float(result.scalar() or 0)

    async def average_duration_between(self, desde: datetime, hasta: datetime) -> float:
        """Duracion promedio de servicio de los turnos no cancelados del rango."""
        result = await self.db.execute(
            select(func.coalesce(func.avg(Service.duration_minutes), 0))
            .select_from(Appointment)
            .join(Service, Appointment.service_id == Service.id)
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
                Appointment.starts_at >= since.replace(tzinfo=None),
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
