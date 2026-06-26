from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.services.model import Service


class ServiceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, service_data: dict[str, Any], store_id: str) -> Service:
        new_service = Service(**service_data, store_id=store_id)
        new_service.public_id = new_service.id
        self.db.add(new_service)
        await self.db.commit()
        await self.db.refresh(new_service)
        return new_service

    async def get_all(self, store_id: str, only_active: bool = True) -> list[Service]:
        query = select(Service).where(Service.store_id == store_id)
        if only_active:
            query = query.where(Service.is_active == True)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, public_id: str, store_id: str) -> Service | None:
        result = await self.db.execute(
            select(Service).where(
                Service.public_id == public_id,
                Service.store_id == store_id,
            )
        )
        return result.scalar_one_or_none()

    async def update(self, service: Service, update_data: dict[str, Any]) -> Service:
        for key, value in update_data.items():
            if value is not None:
                setattr(service, key, value)

        await self.db.commit()
        await self.db.refresh(service)
        return service

    async def soft_delete(self, service: Service) -> None:
        service.is_active = False
        await self.db.commit()
