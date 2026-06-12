from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from modules.services.model import Service


class ServiceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, service_data: dict, store_id: int) -> Service:
        """Crea un nuevo servicio vinculado al store actual."""
        new_service = Service(**service_data, store_id=store_id)
        new_service.public_id = new_service.id
        self.db.add(new_service)
        await self.db.commit()
        await self.db.refresh(new_service)
        return new_service

    async def get_all(self, store_id: int, only_active: bool = True) -> list[Service]:
        """Lista todos los servicios del store. RLS ya filtra por store_id."""
        query = select(Service)
        if only_active:
            query = query.where(Service.is_active == True)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, public_id: str) -> Service | None:
        """Busca un servicio por su ID público."""
        result = await self.db.execute(
            select(Service).where(Service.public_id == public_id)
        )
        return result.scalar_one_or_none()

    async def update(self, service: Service, update_data: dict) -> Service:
        """Actualiza los campos de un servicio."""
        for key, value in update_data.items():
            if value is not None:
                setattr(service, key, value)

        await self.db.commit()
        await self.db.refresh(service)
        return service

    async def soft_delete(self, service: Service) -> None:
        service.is_active = False
        await self.db.commit()
