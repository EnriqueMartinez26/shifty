"""
AppointmentRepository — Acceso puro a datos.

Responsabilidad única: ejecutar queries contra la base de datos.
NO contiene lógica de negocio, validaciones de dominio ni commits
(excepto cuando actúa como operación técnica atómica y simple).
El commit siempre lo realiza la capa de Servicios.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment, AppointmentStatus
from modules.appointments.schemas import AppointmentFilterParams
from modules.services.model import Service
from modules.staff.model import Staff, StaffBlock
from modules.users.model import User


class AppointmentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Lookups de recursos relacionados
    # ------------------------------------------------------------------

    async def get_service_by_public_id(self, public_id: str) -> Service | None:
        res = await self.db.execute(select(Service).where(Service.public_id == public_id))
        return res.scalar_one_or_none()

    async def get_service_by_id(self, service_id: int) -> Service | None:
        res = await self.db.execute(select(Service).where(Service.id == service_id))
        return res.scalar_one_or_none()

    async def get_staff_by_public_id(self, public_id: str) -> Staff | None:
        res = await self.db.execute(select(Staff).where(Staff.id == public_id))
        return res.scalar_one_or_none()

    async def get_staff_by_id(self, staff_id: int) -> Staff | None:
        res = await self.db.execute(select(Staff).where(Staff.id == staff_id))
        return res.scalar_one_or_none()

    async def get_store_by_id(self, store_id: int) -> Store | None:
        from modules.stores.model import Store
        res = await self.db.execute(select(Store).where(Store.id == store_id))
        return res.scalar_one_or_none()

    async def get_by_public_id(self, public_id: str) -> Appointment | None:
        from sqlalchemy.orm import joinedload
        res = await self.db.execute(
            select(Appointment)
            .options(joinedload(Appointment.service), joinedload(Appointment.staff))
            .where(Appointment.public_id == public_id)
        )
        return res.scalar_one_or_none()

    def add(self, appointment: Appointment) -> None:
        """
        Agrega la entidad de turno a la sesión de persistencia actual.
        No se hace commit ni flush; eso es responsabilidad del Unit of Work.
        """
        self.db.add(appointment)

    # ------------------------------------------------------------------
    # Verificaciones de concurrencia y conflictos
    # ------------------------------------------------------------------

    async def lock_staff_row(self, staff_id: int) -> None:
        """
        Bloqueo pesimista (SELECT … FOR UPDATE) sobre la fila del staff.
        Previene overbooking en escenarios de alta concurrencia.
        Siempre se llama dentro de una transacción abierta (por get_db).
        """
        await self.db.execute(
            select(Staff).where(Staff.id == staff_id).with_for_update()
        )

    async def get_conflicting_appointment(
        self,
        staff_id: int,
        starts_at: datetime,
        ends_at: datetime,
        exclude_appointment_id: int | None = None,
    ) -> Appointment | None:
        """
        Retorna el primer turno que solape con el rango [starts_at, ends_at).
        Implementa la fórmula oficial de Sentinel: starts_at < :nuevo.ends_at AND ends_at > :nuevo.starts_at
        """
        from sqlalchemy.orm import joinedload

        # Filtro base: mismo staff y no cancelado
        conditions = [
            Appointment.staff_id == staff_id,
            Appointment.status != AppointmentStatus.CANCELLED.value,
        ]

        # Fórmula de solapamiento (Sentinel 2.2):
        # existente.starts_at < nuevo.ends_at  AND  existente.ends_at > nuevo.starts_at
        # Usamos la columna ends_at almacenada directamente — no hace falta JOIN con Service.
        overlap_condition = and_(
            Appointment.starts_at < ends_at,
            Appointment.ends_at > starts_at,
        )
        conditions.append(overlap_condition)

        query = (
            select(Appointment)
            .options(joinedload(Appointment.service))
            .where(and_(*conditions))
            .order_by(Appointment.starts_at.asc())
            .limit(1)
        )

        if exclude_appointment_id is not None:
            query = query.where(Appointment.id != exclude_appointment_id)

        res = await self.db.execute(query)
        return res.scalar_one_or_none()


    async def get_overlapping_block(
        self, staff_id: int, starts_at: datetime, ends_at: datetime
    ) -> StaffBlock | None:
        """Retorna el primer StaffBlock que solape con el rango dado."""
        res = await self.db.execute(
            select(StaffBlock).where(
                and_(
                    StaffBlock.staff_id == staff_id,
                    StaffBlock.is_active.is_(True),
                    StaffBlock.starts_at < ends_at,
                    StaffBlock.ends_at > starts_at,
                )
            )
        )
        return res.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Listados
    # ------------------------------------------------------------------

    async def get_by_date(
        self, target_date: date
    ) -> list[tuple[Appointment, Service, Staff, User]]:
        """Lista turnos de una fecha para la agenda diaria."""
        from datetime import timezone
        day_start = datetime.combine(target_date, time.min).replace(tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        result = await self.db.execute(
            select(Appointment, Service, Staff, User)
            .join(Service, Appointment.service_id == Service.id)
            .join(Staff, Appointment.staff_id == Staff.id)
            .join(User, Appointment.client_id == User.id)
            .where(
                Appointment.starts_at >= day_start,
                Appointment.starts_at < day_end,
            )
            .order_by(Appointment.starts_at.asc())
        )
        return list(result.all())

    # ------------------------------------------------------------------
    # Búsqueda avanzada con filtros dinámicos
    # ------------------------------------------------------------------

    async def search_appointments(
        self,
        filters: AppointmentFilterParams,
    ) -> tuple[int, list[tuple[Appointment, Service, Staff, User]]]:
        """
        Búsqueda avanzada con filtros dinámicos y paginación.
        Solo construye la query; no interpreta resultados.
        """
        base = (
            select(Appointment, Service, Staff, User)
            .join(Service, Appointment.service_id == Service.id)
            .join(Staff,   Appointment.staff_id == Staff.id)
            .join(User,    Appointment.client_id == User.id)
        )

        conditions = []

        if filters.client_name:
            term = f"%{filters.client_name.strip()}%"
            conditions.append(
                or_(
                    User.first_name.ilike(term),
                    User.last_name.ilike(term),
                    User.email.ilike(term),
                )
            )

        if filters.staff_id:
            conditions.append(Staff.id == filters.staff_id)

        if filters.service_id:
            conditions.append(Service.public_id == filters.service_id)

        if filters.statuses:
            conditions.append(Appointment.status.in_(filters.statuses))

        if filters.from_date:
            conditions.append(
                Appointment.starts_at >= datetime.combine(filters.from_date, time.min)
            )

        if filters.to_date:
            conditions.append(
                Appointment.starts_at < datetime.combine(
                    filters.to_date + timedelta(days=1), time.min
                )
            )

        if conditions:
            base = base.where(and_(*conditions))

        # COUNT total
        count_result = await self.db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar_one()

        # Paginación
        offset = (filters.page - 1) * filters.page_size
        data_query = (
            base
            .order_by(Appointment.starts_at.desc())
            .offset(offset)
            .limit(filters.page_size)
        )

        result = await self.db.execute(data_query)
        return total, list(result.all())

    # ------------------------------------------------------------------
    # Consulta para recordatorios automáticos (Celery Beat)
    # ------------------------------------------------------------------

    async def get_upcoming_for_reminders(
        self, starts_after: datetime, starts_before: datetime
    ) -> list[tuple[Appointment, Service, Staff, User]]:
        """
        Devuelve turnos CONFIRMED o PENDING en el rango horario indicado.
        Usado por la tarea de recordatorios 24h antes.
        """
        result = await self.db.execute(
            select(Appointment, Service, Staff, User)
            .join(Service, Appointment.service_id == Service.id)
            .join(Staff,   Appointment.staff_id == Staff.id)
            .join(User,    Appointment.client_id == User.id)
            .where(
                Appointment.starts_at >= starts_after,
                Appointment.starts_at < starts_before,
                Appointment.status.in_([
                    AppointmentStatus.PENDING.value,
                    AppointmentStatus.CONFIRMED.value,
                ]),
            )
            .order_by(Appointment.starts_at.asc())
        )
        return list(result.all())
