"""
Repositorio publico del turnero.

Responsabilidades:
- Resolucion de stores, servicios y staff para el portal de reservas.
- Identificacion del cliente por telefono.
- Consulta y autogestion publica de turnos.
"""

from datetime import datetime, timedelta, timezone

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


class PublicRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_store_by_slug(self, slug: str) -> Store | None:
        result = await self.db.execute(select(Store).where(Store.slug == slug, Store.is_active == True))
        return result.scalar_one_or_none()

    async def get_store_by_public_id(self, public_id: str) -> Store | None:
        result = await self.db.execute(select(Store).where(Store.public_id == public_id, Store.is_active == True))
        return result.scalar_one_or_none()

    async def get_store_by_id(self, store_id: str) -> Store | None:
        result = await self.db.execute(select(Store).where(Store.id == store_id, Store.is_active == True))
        return result.scalar_one_or_none()

    async def get_services(self, store_id: str) -> list[Service]:
        result = await self.db.execute(
            select(Service).where(Service.store_id == store_id, Service.is_active == True)
        )
        return list(result.scalars().all())

    async def get_service_by_public_id(self, public_id: str) -> Service | None:
        result = await self.db.execute(
            select(Service)
            .join(Store, Service.store_id == Store.id)
            .where(Service.public_id == public_id, Service.is_active == True, Store.is_active == True)
        )
        return result.scalar_one_or_none()

    async def get_staff(self, store_id: str, service_public_id: str | None = None) -> list[Staff]:
        result = await self.db.execute(select(Staff).where(Staff.store_id == store_id, Staff.is_active == True))
        staff_members = list(result.scalars().all())
        if service_public_id:
            staff_members = [
                member for member in staff_members if service_public_id in (member.service_ids or [])
            ]

        for member in staff_members:
            if member.service_ids:
                services_res = await self.db.execute(
                    select(Service).where(
                        Service.store_id == store_id,
                        Service.public_id.in_(member.service_ids),
                        Service.is_active == True,
                    )
                )
                member.services = list(services_res.scalars().all())
            else:
                member.services = []
        return staff_members

    async def get_or_create_client(
        self,
        store_id: str,
        phone: str,
        name: str,
        email: str | None,
    ) -> User:
        result = await self.db.execute(
            select(User).where(User.phone == phone, User.store_id == store_id, User.role == UserRole.CLIENT)
        )
        existing = result.scalar_one_or_none()

        if existing:
            if email and (not existing.email or existing.email.endswith(".noreply")):
                existing.email = email
                await self.db.flush()
            if name and not existing.first_name:
                existing.first_name = name
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
                    existing_by_email.first_name = name
                await self.db.flush()
                return existing_by_email

        technical_email = email or f"{phone}@store{store_id}.noreply"
        new_client = User(
            email=technical_email,
            hashed_password=hash_password(str(ulid.ULID())),
            first_name=name,
            last_name=None,
            phone=phone,
            role=UserRole.CLIENT,
            store_id=store_id,
        )
        self.db.add(new_client)
        await self.db.flush()
        return new_client

    async def _staff_has_schedule_for_slot(self, staff_id: str, starts_at: datetime, ends_at: datetime) -> bool:
        weekday = starts_at.weekday()
        start_time = starts_at.astimezone(timezone.utc).time().replace(tzinfo=None)
        end_time = ends_at.astimezone(timezone.utc).time().replace(tzinfo=None)
        schedules_result = await self.db.execute(
            select(Schedule).where(Schedule.staff_id == staff_id, Schedule.day_of_week == weekday)
        )
        schedules = list(schedules_result.scalars().all())
        return any(schedule.start_time <= start_time and schedule.end_time >= end_time for schedule in schedules)

    async def _staff_has_overlapping_block(self, staff_id: str, starts_at: datetime, ends_at: datetime) -> bool:
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
        idempotency_key: str,
        initial_status: str = AppointmentStatus.PENDING.value,
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
        qualified_staff = await self.get_staff(store_id, service_public_id=service_public_id)

        if staff_public_id:
            candidates = [member for member in qualified_staff if member.public_id == staff_public_id]
            if not candidates:
                raise ValueError("El profesional no realiza el servicio seleccionado")
        else:
            candidates = sorted(qualified_staff, key=lambda member: (member.display_name or "", member.public_id))

        if not candidates:
            raise ValueError("No hay profesionales disponibles para este servicio")

        selected_staff: Staff | None = None
        for staff in candidates:
            if not await self._staff_has_schedule_for_slot(staff.id, starts_at, ends_at):
                continue
            if await self._staff_has_overlapping_block(staff.id, starts_at, ends_at):
                continue

            await self.db.execute(select(Staff).where(Staff.id == staff.id).with_for_update())
            conflict_res = await self.db.execute(
                select(Appointment).where(
                    Appointment.staff_id == staff.id,
                    Appointment.status.in_(
                        [
                            AppointmentStatus.PENDING.value,
                            AppointmentStatus.PENDING_PAYMENT.value,
                            AppointmentStatus.CONFIRMED.value,
                        ]
                    ),
                    Appointment.starts_at < ends_at,
                    Appointment.ends_at > starts_at,
                ).limit(1)
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
            client_name=client.first_name or client.email,
            client_email=client.email,
            client_phone=client.phone,
            notes=notes,
            idempotency_key=idempotency_key,
            status=initial_status,
        )
        self.db.add(new_appointment)
        await self.db.flush()
        await self.db.refresh(new_appointment)

        return new_appointment, service, selected_staff

    async def get_client_by_phone(self, store_id: str, phone: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.phone == phone, User.store_id == store_id, User.role == UserRole.CLIENT)
        )
        return result.scalar_one_or_none()

    async def get_client_appointments(self, client_id: str, store_id: str) -> list[Appointment]:
        result = await self.db.execute(
            select(Appointment)
            .where(Appointment.client_id == client_id, Appointment.store_id == store_id)
            .options(selectinload(Appointment.service), selectinload(Appointment.staff))
            .order_by(Appointment.starts_at.desc())
        )
        return list(result.scalars().all())

    async def get_appointment_by_public_id_and_client(self, public_id: str, client_id: str) -> Appointment | None:
        result = await self.db.execute(
            select(Appointment)
            .where(Appointment.public_id == public_id, Appointment.client_id == client_id)
            .options(selectinload(Appointment.service), selectinload(Appointment.staff))
        )
        return result.scalar_one_or_none()
