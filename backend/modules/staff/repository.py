from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.security import hash_password
from modules.services.model import Service
from modules.staff.model import Schedule, Staff
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
        user_res = await self.db.execute(
            select(User).where(User.email == data["email"])
        )
        if user_res.scalar_one_or_none():
            raise ValueError("Ya existe un usuario con ese email")

        services = await self._get_services_for_store(service_public_ids, store_id)

        user = User(
            email=data["email"],
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
            email=data["email"],
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
        for member in staff_members:
            await self._hydrate_services(member)
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

    async def add_schedule(
        self, staff: Staff, schedule_data: dict[str, Any], store_id: str
    ) -> Schedule:
        new_schedule = Schedule(**schedule_data, staff_id=staff.id, store_id=store_id)
        self.db.add(new_schedule)
        await self.db.commit()
        await self.db.refresh(new_schedule)
        return new_schedule

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
        if email is not None and email != staff.email:
            existing_res = await self.db.execute(
                select(User).where(User.email == email, User.id != staff.id)
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

        await self.db.commit()
        await self.db.refresh(staff)
        return staff

    async def soft_delete(self, staff: Staff) -> None:
        staff.is_active = False
        user_res = await self.db.execute(select(User).where(User.email == staff.email))
        user = user_res.scalar_one_or_none()
        if user:
            user.is_active = False
        await self.db.commit()
