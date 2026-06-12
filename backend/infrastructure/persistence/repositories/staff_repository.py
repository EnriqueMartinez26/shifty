from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from domain.entities.staff import Staff
from domain.repositories.staff_repository import IStaffRepository
from infrastructure.persistence.models.staff import StaffModel


class StaffRepository(IStaffRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_id(self, id: str) -> Optional[Staff]:
        stmt = select(StaffModel).where(StaffModel.id == id)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._map_to_entity(model) if model else None

    async def find_all(self, store_id: str) -> List[Staff]:
        stmt = select(StaffModel).where(StaffModel.store_id == store_id)
        result = await self.session.execute(stmt)
        return [self._map_to_entity(m) for m in result.scalars().all()]

    async def save(self, staff: Staff) -> Staff:
        model = await self.session.get(StaffModel, staff.id)
        if not model:
            model = StaffModel(
                id=staff.id,
                first_name=staff.first_name,
                last_name=staff.last_name,
                display_name=staff.display_name,
                email=staff.email,
                store_id=staff.store_id,
                service_ids=staff.service_ids,
                is_active=staff.is_active,
                created_at=staff.created_at,
                updated_at=staff.updated_at,
            )
            self.session.add(model)
        else:
            model.first_name = staff.first_name
            model.last_name = staff.last_name
            model.display_name = staff.display_name
            model.service_ids = staff.service_ids
            model.is_active = staff.is_active
            model.updated_at = staff.updated_at

        await self.session.flush()
        return self._map_to_entity(model)

    async def delete(self, id: str) -> None:
        model = await self.session.get(StaffModel, id)
        if model:
            await self.session.delete(model)
            await self.session.flush()

    def _map_to_entity(self, model: StaffModel) -> Staff:
        return Staff(
            id=model.id,
            first_name=model.first_name,
            last_name=model.last_name,
            display_name=model.display_name,
            email=model.email,
            store_id=model.store_id,
            service_ids=model.service_ids,
            is_active=model.is_active,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
