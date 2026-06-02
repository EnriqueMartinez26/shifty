"""
Repositorio Público del Turnero.

Responsabilidades:
- Resolución de stores, servicios y staff para el portal de reservas.
- get_or_create_client: Identifica al cliente por TELÉFONO (no email).
- Portal del cliente: consulta y cancelación de turnos sin login.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import ulid

from core.security import hash_password
from modules.appointments.model import Appointment, AppointmentStatus
from modules.services.model import Service
from modules.staff.model import Staff
from modules.stores.model import Store
from modules.users.model import User, UserRole


class PublicRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Resolvers de Store
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Catálogo público
    # ------------------------------------------------------------------

    async def get_services(self, store_id: int) -> list[Service]:
        result = await self.db.execute(
            select(Service).where(
                Service.store_id == store_id,
                Service.is_active == True,
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

    async def get_staff(self, store_id: int, service_public_id: str | None = None) -> list[Staff]:
        result = await self.db.execute(
            select(Staff)
            .where(Staff.store_id == store_id, Staff.is_active == True)
        )
        staff_members = list(result.scalars().all())
        if service_public_id:
            staff_members = [
                member
                for member in staff_members
                if service_public_id in (member.service_ids or [])
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

    # ------------------------------------------------------------------
    # Fase 1: Identificación de Cliente por TELÉFONO
    # ------------------------------------------------------------------

    async def get_or_create_client(
        self,
        store_id: int,
        phone: str,          # ← clave de búsqueda primaria dentro del store
        name: str,           # nombre completo (se guarda en first_name)
        email: str | None,   # optional — solo para notificaciones
    ) -> User:
        """
        Busca al cliente por TELÉFONO (primario) o EMAIL (secundario) dentro del store.
        - Si existe por teléfono → lo retorna y actualiza email si falta.
        - Si existe por email pero distinto teléfono → lo retorna (mismo cliente real).
        - Si no existe → crea un usuario tipo CLIENT con contraseña inutilizable.

        Previene UniqueViolationError cuando el mismo email real ya está registrado
        bajo un teléfono diferente o al volver a reservar por segunda vez.
        """
        # 1. Buscar por teléfono (criterio principal)
        result = await self.db.execute(
            select(User).where(
                User.phone == phone,
                User.store_id == store_id,
                User.role == UserRole.CLIENT,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Actualizar email si se proveyó uno nuevo y el registro lo tiene vacío
            if email and not existing.email:
                existing.email = email
                await self.db.flush()
            return existing

        # 2. Si se proveyó email, buscar por email para evitar duplicados
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
                # Mismo cliente real, actualizar teléfono si cambió
                if not existing_by_email.phone:
                    existing_by_email.phone = phone
                    await self.db.flush()
                return existing_by_email

        # 3. No existe → crear nuevo cliente
        # Email técnico si no se proveyó (necesario por restricción UNIQUE en users.email)
        # Formato: {phone}@store{store_id}.noreply — nunca colisiona con emails reales
        technical_email = email or f"{phone}@store{store_id}.noreply"

        new_client = User(
            email=technical_email,
            hashed_password=hash_password(str(ulid.ULID())),  # inutilizable — no puede loguearse
            first_name=name,
            last_name=None,
            phone=phone,
            role=UserRole.CLIENT,
            store_id=store_id,
        )
        self.db.add(new_client)
        await self.db.flush()
        return new_client

    # ------------------------------------------------------------------
    # Creación de turno público (con bloqueo pesimista)
    # ------------------------------------------------------------------

    async def create_appointment(
        self,
        store_id: int,
        service_public_id: str,
        staff_public_id: str,
        starts_at,
        client: User,
        notes: str | None,
        idempotency_key: str,
    ) -> tuple[Appointment, Service, Staff]:
        """
        Crea un turno con control de concurrencia (FOR UPDATE).
        Retorna (appointment, service, staff) para la respuesta.
        """
        # 1. Resolver servicio y staff
        svc_res = await self.db.execute(
            select(Service).where(
                Service.public_id == service_public_id,
                Service.store_id == store_id,
                Service.is_active == True,
            )
        )
        service = svc_res.scalar_one_or_none()

        stf_res = await self.db.execute(
            select(Staff).where(
                Staff.id == staff_public_id,
                Staff.store_id == store_id,
                Staff.is_active == True,
            )
        )
        staff = stf_res.scalar_one_or_none()

        if not service or not staff:
            raise ValueError("Servicio o profesional no encontrado")
        if service_public_id not in (staff.service_ids or []):
            raise ValueError("El profesional no realiza el servicio seleccionado")

        ends_at = starts_at + timedelta(minutes=service.duration_minutes)

        # 2. Bloqueo pesimista — previene overbooking bajo alta concurrencia
        await self.db.execute(
            select(Staff).where(Staff.id == staff.id).with_for_update()
        )

        from sqlalchemy import func  # noqa: F401 – kept for other callers if any
        # 3. Verificar conflicto post-lock
        # Usamos ends_at almacenado directamente en lugar de make_interval.
        conflict_res = await self.db.execute(
            select(Appointment)
            .where(
                Appointment.staff_id == staff.id,
                Appointment.status != AppointmentStatus.CANCELLED.value,
                Appointment.starts_at < ends_at,
                Appointment.ends_at > starts_at,
            )
            .limit(1)
        )
        if conflict_res.scalar_one_or_none():
            raise ValueError("El horario ya está ocupado. Por favor elegí otro.")

        # 4. Crear turno
        new_appointment = Appointment(
            store_id=store_id,
            staff_id=staff.id,
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
        )
        self.db.add(new_appointment)
        await self.db.flush()
        await self.db.refresh(new_appointment)

        return new_appointment, service, staff

    # ------------------------------------------------------------------
    # Fase 8: Portal del Cliente — Consulta de Turnos por Teléfono
    # ------------------------------------------------------------------

    async def get_client_by_phone(self, store_id: int, phone: str) -> User | None:
        """Busca al cliente por teléfono en el store."""
        result = await self.db.execute(
            select(User).where(
                User.phone == phone,
                User.store_id == store_id,
                User.role == UserRole.CLIENT,
            )
        )
        return result.scalar_one_or_none()

    async def get_client_appointments(
        self,
        client_id: int,
        store_id: int,
    ) -> list[tuple[Appointment, Service, Staff]]:
        """
        Retorna los turnos del cliente con servicio y staff expandidos.
        Ordenados por fecha descendente (turnos futuros primero, luego histórico).
        """
        result = await self.db.execute(
            select(Appointment)
            .where(
                Appointment.client_id == client_id,
                Appointment.store_id == store_id,
            )
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.staff),
            )
            .order_by(Appointment.starts_at.desc())
        )
        return list(result.scalars().all())

    async def get_appointment_by_public_id_and_client(
        self,
        public_id: str,
        client_id: int,
    ) -> Appointment | None:
        """
        Busca un turno verificando que pertenezca al cliente.
        Doble validación: public_id + client_id para seguridad.
        """
        result = await self.db.execute(
            select(Appointment)
            .where(
                Appointment.public_id == public_id,
                Appointment.client_id == client_id,
            )
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.staff),
            )
        )
        return result.scalar_one_or_none()
