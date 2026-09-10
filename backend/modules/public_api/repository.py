"""
Repositorio publico del turnero.

Responsabilidades:
- Resolucion de stores, servicios y staff para el portal de reservas.
- Identificacion del cliente por telefono.
- Consulta y autogestion publica de turnos.
"""

from decimal import Decimal
from core.utils import ARGENTINA_TZ
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import ulid

from core.security import hash_password
from modules.appointments.model import Appointment, AppointmentStatus
from modules.services.model import Service
from modules.staff.model import Schedule, Staff, StaffBlock
from modules.stores.model import Store
from modules.users.model import User, UserRole

# Los clientes creados en el booking publico NO inician sesion (login/reset les
# esta negado), asi que su hash de password nunca se verifica. Se computa UNA
# sola vez al importar y se reusa, en vez de correr bcrypt (sincrono, 12 rounds,
# ~250ms) en el event loop por cada alta anonima: era un vector de DoS. Sigue
# siendo un hash bcrypt valido, asi que un verify eventual devuelve False sin
# romper (no un formato invalido que lance excepcion).
_UNUSABLE_CLIENT_PASSWORD_HASH = hash_password(str(ulid.ULID()))


class PublicRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_store_by_slug(self, slug: str) -> Store | None:
        result = await self.db.execute(
            select(Store).where(Store.slug == slug, Store.is_active == True)
        )
        return result.scalar_one_or_none()

    async def get_store_by_public_id(self, public_id: str) -> Store | None:
        result = await self.db.execute(
            select(Store).where(Store.public_id == public_id, Store.is_active == True)
        )
        return result.scalar_one_or_none()

    async def get_store_by_id(self, store_id: str) -> Store | None:
        result = await self.db.execute(
            select(Store).where(Store.id == store_id, Store.is_active == True)
        )
        return result.scalar_one_or_none()

    async def get_services(self, store_id: str) -> list[Service]:
        result = await self.db.execute(
            select(Service).where(
                Service.store_id == store_id, Service.is_active == True
            )
        )
        return list(result.scalars().all())

    async def get_service_by_public_id(self, public_id: str) -> Service | None:
        result = await self.db.execute(
            select(Service)
            .join(Store, Service.store_id == Store.id)
            .where(
                Service.public_id == public_id,
                Service.is_active == True,
                Store.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def get_staff(
        self, store_id: str, service_public_id: str | None = None
    ) -> list[Staff]:
        result = await self.db.execute(
            select(Staff)
            .options(selectinload(Staff.services))
            .where(Staff.store_id == store_id, Staff.is_active == True)
        )
        staff_members = list(result.scalars().all())
        if service_public_id:
            staff_members = [
                member
                for member in staff_members
                if service_public_id in (member.service_ids or [])
            ]

        # Antes esto ejecutaba un select(Service) POR CADA miembro (N+1) en el
        # portal publico de reservas. Se batchea en UNA sola query con todos los
        # service_ids y se reparte en memoria, preservando la semantica exacta
        # (activos y pertenecientes al service_ids de cada miembro).
        wanted_ids = {
            sid for member in staff_members for sid in (member.service_ids or [])
        }
        services_by_id: dict[str, Service] = {}
        if wanted_ids:
            services_res = await self.db.execute(
                select(Service).where(
                    Service.store_id == store_id,
                    Service.public_id.in_(wanted_ids),
                    Service.is_active == True,
                )
            )
            services_by_id = {
                service.public_id: service for service in services_res.scalars().all()
            }
        for member in staff_members:
            member.services = [
                services_by_id[sid]
                for sid in (member.service_ids or [])
                if sid in services_by_id
            ]
        return staff_members

    async def get_or_create_client(
        self,
        store_id: str,
        phone: str,
        name: str,
        email: str | None,
    ) -> User:
        # Dos clientes con el mismo telefono (alta vieja sin unicidad) rompian
        # con MultipleResultsFound -> 500. Se toma el mas reciente.
        result = await self.db.execute(
            select(User)
            .where(
                User.phone == phone,
                User.store_id == store_id,
                User.role == UserRole.CLIENT,
            )
            .order_by(User.created_at.desc())
            .limit(1)
        )
        existing = result.scalars().first()

        if existing:
            if email and (not existing.email or existing.email.endswith(".noreply")):
                existing.email = email
                await self.db.flush()
            if name and not existing.first_name:
                existing.full_name = name
            return existing

        if email:
            result_by_email = await self.db.execute(
                select(User).where(
                    User.email == email,
                    User.store_id == store_id,
                    User.role == UserRole.CLIENT,
                )
            )
            existing_by_email = result_by_email.scalar_one_or_none()
            if existing_by_email:
                if not existing_by_email.phone:
                    existing_by_email.phone = phone
                if name and not existing_by_email.first_name:
                    existing_by_email.full_name = name
                await self.db.flush()
                return existing_by_email

        technical_email = email or f"{phone}@store{store_id}.noreply"
        new_client = User(
            email=technical_email,
            hashed_password=_UNUSABLE_CLIENT_PASSWORD_HASH,
            full_name=name,
            phone=phone,
            role=UserRole.CLIENT,
            store_id=store_id,
        )
        self.db.add(new_client)
        await self.db.flush()
        return new_client

    async def _staff_has_schedule_for_slot(
        self, staff_id: str, starts_at: datetime, ends_at: datetime
    ) -> bool:
        # El horario del profesional esta cargado en hora ARGENTINA (09:00 a
        # 18:00); el turno llega como instante UTC. Comparar en UTC rechazaba
        # las ultimas 3 horas de cada jornada y todo turno posterior a las
        # 21:00 (cae en el dia UTC siguiente). 2026-09-10.
        local_start = starts_at.astimezone(ARGENTINA_TZ)
        local_end = ends_at.astimezone(ARGENTINA_TZ)
        weekday = local_start.weekday()
        start_time = local_start.time().replace(tzinfo=None)
        end_time = local_end.time().replace(tzinfo=None)
        schedules_result = await self.db.execute(
            select(Schedule).where(
                Schedule.staff_id == staff_id, Schedule.day_of_week == weekday
            )
        )
        schedules = list(schedules_result.scalars().all())
        return any(
            schedule.start_time <= start_time and schedule.end_time >= end_time
            for schedule in schedules
        )

    async def _staff_has_overlapping_block(
        self, staff_id: str, starts_at: datetime, ends_at: datetime
    ) -> bool:
        blocks_result = await self.db.execute(
            select(StaffBlock).where(
                StaffBlock.staff_id == staff_id,
                StaffBlock.is_active.is_(True),
                StaffBlock.starts_at < ends_at,
                StaffBlock.ends_at > starts_at,
            )
        )
        return blocks_result.scalar_one_or_none() is not None

    async def create_appointment(
        self,
        store_id: str,
        service_public_id: str,
        staff_public_id: str | None,
        starts_at: datetime,
        client: User,
        notes: str | None,
        intake_answers: dict[str, str] | None,
        idempotency_key: str,
        initial_status: str = AppointmentStatus.PENDING.value,
        buffer_minutes: int = 0,
        price_amount: Decimal | None = None,
    ) -> tuple[Appointment, Service, Staff]:
        svc_res = await self.db.execute(
            select(Service).where(
                Service.public_id == service_public_id,
                Service.store_id == store_id,
                Service.is_active == True,
            )
        )
        service = svc_res.scalar_one_or_none()
        if not service:
            raise ValueError("Servicio no encontrado")

        ends_at = starts_at + timedelta(minutes=service.duration_minutes)
        qualified_staff = await self.get_staff(
            store_id, service_public_id=service_public_id
        )

        if staff_public_id:
            candidates = [
                member
                for member in qualified_staff
                if member.public_id == staff_public_id
            ]
            if not candidates:
                raise ValueError("El profesional no realiza el servicio seleccionado")
        else:
            candidates = sorted(
                qualified_staff,
                key=lambda member: (member.display_name or "", member.public_id),
            )

        if not candidates:
            raise ValueError("No hay profesionales disponibles para este servicio")

        selected_staff: Staff | None = None
        for staff in candidates:
            if not await self._staff_has_schedule_for_slot(
                staff.id, starts_at, ends_at
            ):
                continue

            # Lock ANTES de leer bloqueos y conflictos: leer el bloqueo sin el
            # lock dejaba colar una reserva dentro de un bloqueo recien creado
            # (carrera reproducida en tests/postgres/test_pg_bloqueos.py).
            await self.db.execute(
                select(Staff).where(Staff.id == staff.id).with_for_update()
            )
            if await self._staff_has_overlapping_block(staff.id, starts_at, ends_at):
                continue
            # Mismo criterio que el panel (get_conflicting_appointment): el
            # turno vecino se ensancha por el buffer de la tienda a cada lado.
            buffer = timedelta(minutes=max(0, buffer_minutes))
            conflict_res = await self.db.execute(
                select(Appointment)
                .where(
                    Appointment.staff_id == staff.id,
                    Appointment.status.in_(
                        [
                            AppointmentStatus.PENDING.value,
                            AppointmentStatus.PENDING_PAYMENT.value,
                            AppointmentStatus.CONFIRMED.value,
                        ]
                    ),
                    Appointment.starts_at < ends_at + buffer,
                    Appointment.ends_at > starts_at - buffer,
                )
                .limit(1)
            )
            if conflict_res.scalar_one_or_none():
                continue

            selected_staff = staff
            break

        if not selected_staff:
            if staff_public_id:
                raise ValueError("El horario ya esta ocupado. Por favor elegi otro.")
            raise ValueError("No hay profesionales disponibles para ese horario")

        new_appointment = Appointment(
            store_id=store_id,
            staff_id=selected_staff.id,
            service_id=service.id,
            client_id=client.id,
            starts_at=starts_at,
            ends_at=ends_at,
            duration_minutes=service.duration_minutes,
            client_name=client.full_name or client.email,
            client_email=client.email,
            client_phone=client.phone,
            notes=notes,
            intake_answers=intake_answers or {},
            idempotency_key=idempotency_key,
            status=initial_status,
            # Precio congelado al reservar (el panel ya lo hacia): un cobro
            # manual posterior no debe usar el precio de lista de hoy.
            price_amount=(
                price_amount
                if price_amount is not None
                else Decimal(str(service.price or 0))
            ),
        )
        self.db.add(new_appointment)
        await self.db.flush()
        await self.db.refresh(new_appointment)

        return new_appointment, service, selected_staff

    async def get_client_by_phone(self, store_id: str, phone: str) -> User | None:
        result = await self.db.execute(
            select(User)
            .where(
                User.phone == phone,
                User.store_id == store_id,
                User.role == UserRole.CLIENT,
            )
            .order_by(User.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_client_appointments(
        self, client_id: str, store_id: str
    ) -> list[Appointment]:
        result = await self.db.execute(
            select(Appointment)
            .where(Appointment.client_id == client_id, Appointment.store_id == store_id)
            .options(selectinload(Appointment.service), selectinload(Appointment.staff))
            .order_by(Appointment.starts_at.desc())
        )
        return list(result.scalars().all())

    async def get_appointment_by_public_id_and_client(
        self, public_id: str, client_id: str
    ) -> Appointment | None:
        result = await self.db.execute(
            select(Appointment)
            .where(Appointment.id == public_id, Appointment.client_id == client_id)
            .options(selectinload(Appointment.service), selectinload(Appointment.staff))
        )
        return result.scalar_one_or_none()
