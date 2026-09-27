from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.services.model import Service


class ServiceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, service_data: dict[str, Any], store_id: str) -> Service:
        # `public_id` e `id` son dos columnas con su propio `default`, que
        # SQLAlchemy resuelve por separado en el INSERT. Aca vivia
        # `new_service.public_id = new_service.id`, que corria ANTES del flush
        # -con `id` todavia en None- y no hacia nada salvo documentar un
        # invariante falso: los dos ULID siempre fueron distintos
        # (AUD2-B6-08 / B6-09, 2026-09-20). Que deban serlo o no es decision
        # del dueno; esto solo saca la linea muerta.
        new_service = Service(**service_data, store_id=store_id)
        self.db.add(new_service)
        await self.db.commit()
        await self.db.refresh(new_service)
        return new_service

    async def get_all(
        self,
        store_id: str,
        only_active: bool = True,
        limit: int = 500,
        offset: int = 0,
    ) -> list[Service]:
        query = select(Service).where(Service.store_id == store_id)
        if only_active:
            query = query.where(Service.is_active == True)

        # Orden de alta explicito: sin ORDER BY, LIMIT/OFFSET no es estable
        # entre paginas. El id (ULID) desempata altas del mismo instante.
        query = (
            query.order_by(Service.created_at, Service.id).limit(limit).offset(offset)
        )
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
        # Aplica lo que recibe: el router ya manda solo los campos enviados
        # (exclude_unset), asi que un None aca es un null explicito (B6-04).
        for key, value in update_data.items():
            setattr(service, key, value)

        await self.db.commit()
        await self.db.refresh(service)
        return service

    async def soft_delete(self, service: Service) -> None:
        service.is_active = False
        await self.db.commit()
