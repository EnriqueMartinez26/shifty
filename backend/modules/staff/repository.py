from datetime import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.security import hash_password
from modules.services.model import Service
from modules.staff.model import Schedule, Staff
from modules.auth.service import revoke_sessions_for_user
from modules.users.model import User, UserRole
import ulid


class StaffRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get_services_for_store(
        self, service_public_ids: list[str], store_id: str
    ) -> list[Service]:
        if not service_public_ids:
            return []

        result = await self.db.execute(
            select(Service).where(
                Service.public_id.in_(service_public_ids),
                Service.store_id == store_id,
                Service.is_active == True,
            )
        )
        services = list(result.scalars().all())
        if len(services) != len(set(service_public_ids)):
            raise ValueError(
                "Uno o m?s servicios no existen o no pertenecen al negocio"
            )
        return services

    async def _hydrate_services(self, member: Staff) -> None:
        if member.service_ids:
            member.services = await self._get_services_for_store(
                member.service_ids,
                member.store_id,
            )
        else:
            member.services = []

    async def create(
        self, data: dict[str, Any], store_id: str, service_public_ids: list[str]
    ) -> Staff:
        # Normalizamos el email igual que el login (lower). Sin esto, "Pro@x.com"
        # y "pro@x.com" conviven como dos usuarios y el login case-insensitive
        # encuentra ambos y explota con MultipleResultsFound.
        email = str(data["email"]).strip().lower()
        user_res = await self.db.execute(
            select(User).where(func.lower(User.email) == email)
        )
        if user_res.scalar_one_or_none():
            raise ValueError("Ya existe un usuario con ese email")

        services = await self._get_services_for_store(service_public_ids, store_id)

        user = User(
            email=email,
            hashed_password=hash_password(str(ulid.ULID())),
            first_name=data["first_name"],
            last_name=data["last_name"],
            role=UserRole.STAFF,
            store_id=store_id,
        )
        self.db.add(user)
        await self.db.flush()

        new_staff = Staff(
            id=user.id,
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=email,
            display_name=data["display_name"],
            store_id=store_id,
            service_ids=[service.public_id for service in services],
        )
        new_staff.services = services
        self.db.add(new_staff)
        await self.db.commit()
        await self.db.refresh(new_staff)
        return new_staff

    async def get_all(self, store_id: str) -> list[Staff]:
        result = await self.db.execute(
            select(Staff)
            .where(
                Staff.store_id == store_id,
                Staff.is_active == True,
            )
            .options(
                selectinload(Staff.schedules),
                selectinload(Staff.services),
            )
        )
        staff_members = list(result.scalars().all())
        # ``services`` ya viene cargado por selectinload en una sola query.
        # Antes esto re-consultaba por cada miembro (N+1); ahora se filtra en
        # memoria a los activos, que es lo unico que agregaba la re-consulta.
        for member in staff_members:
            member.services = [s for s in member.services if s.is_active]
        return staff_members

    async def get_by_id(self, public_id: str, store_id: str) -> Staff | None:
        result = await self.db.execute(
            select(Staff)
            .where(
                Staff.id == public_id,
                Staff.store_id == store_id,
            )
            .options(
                selectinload(Staff.schedules),
                selectinload(Staff.services),
            )
        )
        member = result.scalar_one_or_none()
        if member:
            await self._hydrate_services(member)
        return member

    async def _assert_no_overlap(
        self,
        staff: Staff,
        *,
        day_of_week: int,
        start: time,
        end: time,
        exclude_id: str | None = None,
    ) -> None:
        """Impide franjas superpuestas o duplicadas para el mismo dia.

        Antes se podia cargar dos veces el mismo rango y el booking publico
        mostraba cada horario repetido: el cliente veia "09:00" dos veces.
        Dos franjas separadas el mismo dia (manana y tarde) siguen siendo
        validas mientras no se toquen.
        """
        filtros = [Schedule.staff_id == staff.id, Schedule.day_of_week == day_of_week]
        if exclude_id:
            filtros.append(Schedule.id != exclude_id)
        existentes = (await self.db.execute(select(Schedule).where(*filtros))).scalars()

        for otro in existentes:
            if start < otro.end_time and end > otro.start_time:
                raise ValueError(
                    "El horario se superpone con otra franja de ese dia "
                    f"({otro.start_time.strftime('%H:%M')}-"
                    f"{otro.end_time.strftime('%H:%M')})"
                )

    async def add_schedule(
        self, staff: Staff, schedule_data: dict[str, Any], store_id: str
    ) -> Schedule:
        await self._assert_no_overlap(
            staff,
            day_of_week=schedule_data["day_of_week"],
            start=schedule_data["start_time"],
            end=schedule_data["end_time"],
        )
        new_schedule = Schedule(**schedule_data, staff_id=staff.id, store_id=store_id)
        self.db.add(new_schedule)
        await self.db.commit()
        await self.db.refresh(new_schedule)
        return new_schedule

    async def get_schedule(self, staff: Staff, schedule_id: str) -> Schedule | None:
        result = await self.db.execute(
            select(Schedule).where(
                Schedule.id == schedule_id, Schedule.staff_id == staff.id
            )
        )
        return result.scalar_one_or_none()

    async def update_schedule(
        self, staff: Staff, schedule: Schedule, cambios: dict[str, Any]
    ) -> Schedule:
        day = cambios.get("day_of_week", schedule.day_of_week)
        start = cambios.get("start_time", schedule.start_time)
        end = cambios.get("end_time", schedule.end_time)
        if start >= end:
            raise ValueError("La hora de inicio debe ser anterior a la de fin")

        await self._assert_no_overlap(
            staff, day_of_week=day, start=start, end=end, exclude_id=schedule.id
        )

        schedule.day_of_week = day
        schedule.start_time = start
        schedule.end_time = end
        await self.db.commit()
        await self.db.refresh(schedule)
        return schedule

    async def delete_schedule(self, schedule: Schedule) -> None:
        await self.db.delete(schedule)
        await self.db.commit()

    async def update_services(
        self, staff: Staff, service_public_ids: list[str]
    ) -> Staff:
        services_list = await self._get_services_for_store(
            service_public_ids,
            staff.store_id,
        )
        staff.service_ids = [service.public_id for service in services_list]
        staff.services = services_list
        await self.db.commit()
        await self.db.refresh(staff)
        return staff

    async def update_profile(
        self,
        staff: Staff,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        display_name: str | None = None,
        service_public_ids: list[str] | None = None,
        is_active: bool | None = None,
    ) -> Staff:
        if email is not None:
            email = email.strip().lower()
        if email is not None and email != staff.email:
            existing_res = await self.db.execute(
                select(User).where(func.lower(User.email) == email, User.id != staff.id)
            )
            if existing_res.scalar_one_or_none():
                raise ValueError("Ya existe un usuario con ese email")

        if first_name is not None:
            staff.first_name = first_name
        if last_name is not None:
            staff.last_name = last_name
        if email is not None:
            staff.email = email
        if display_name is not None:
            staff.display_name = display_name
        if is_active is not None:
            staff.is_active = is_active
        if service_public_ids is not None:
            services_list = await self._get_services_for_store(
                service_public_ids,
                staff.store_id,
            )
            staff.service_ids = [service.public_id for service in services_list]
            staff.services = services_list

        user_res = await self.db.execute(select(User).where(User.id == staff.id))
        user = user_res.scalar_one_or_none()
        if user:
            user.first_name = staff.first_name
            user.last_name = staff.last_name
            user.email = staff.email
            user.full_name = f"{staff.first_name or ''} {staff.last_name or ''}".strip()
            if is_active is not None:
                user.is_active = is_active
                # Desactivar al profesional corta sus sesiones vivas, igual que
                # en users/superadmin: sin esto, al reactivarlo sus refresh
                # tokens de 30 dias volverian a funcionar.
                if not is_active:
                    await revoke_sessions_for_user(self.db, user.id)

        await self.db.commit()
        await self.db.refresh(staff)
        return staff

    async def soft_delete(self, staff: Staff) -> None:
        staff.is_active = False
        user_res = await self.db.execute(select(User).where(User.email == staff.email))
        user = user_res.scalar_one_or_none()
        if user:
            user.is_active = False
            await revoke_sessions_for_user(self.db, user.id)
        await self.db.commit()
