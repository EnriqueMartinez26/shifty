from collections import defaultdict
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.services.model import Service, ServiceAddon


class ServiceRepository:
    """Consultas y escrituras del catalogo, sin commit.

    Solo hace ``flush``: el commit es del service (``ServiceCatalogService``,
    B6-05, 2026-09-30), para que el PATCH y el borrado de la imagen huerfana
    cierren en UNA transaccion.
    """

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
        await self.db.flush()
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

        await self.db.flush()
        await self.db.refresh(service)
        return service

    async def soft_delete(self, service: Service) -> None:
        service.is_active = False
        await self.db.flush()

    async def lock(self, public_id: str, store_id: str) -> Service | None:
        """El servicio con ``FOR UPDATE`` (regla 4): dos reemplazos de sus
        adicionales a la vez se serializan aca."""
        result = await self.db.execute(
            select(Service)
            .where(Service.public_id == public_id, Service.store_id == store_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def addons_for(
        self, store_id: str, service_ids: Sequence[str]
    ) -> dict[str, list[ServiceAddon]]:
        """Adicionales de varios servicios en UNA consulta (``in_()``, regla
        12), agrupados por ``services.id`` y en orden de ``position``."""
        por_servicio: dict[str, list[ServiceAddon]] = defaultdict(list)
        if not service_ids:
            return por_servicio
        result = await self.db.execute(
            select(ServiceAddon)
            .where(
                ServiceAddon.store_id == store_id,
                ServiceAddon.service_id.in_(list(service_ids)),
            )
            .order_by(ServiceAddon.service_id, ServiceAddon.position)
        )
        for addon in result.scalars().all():
            por_servicio[addon.service_id].append(addon)
        return por_servicio

    async def replace_addons(
        self, service: Service, addons: Sequence[dict[str, Any]]
    ) -> list[ServiceAddon]:
        """Reemplaza el conjunto de adicionales del servicio (borrado fisico).

        El llamador ya tomo el lock del servicio. Los turnos que eligieron un
        adicional borrado guardan su snapshot: no dependen de la fila.
        """
        await self.db.execute(
            delete(ServiceAddon).where(
                ServiceAddon.store_id == service.store_id,
                ServiceAddon.service_id == service.id,
            )
        )
        nuevos = [
            ServiceAddon(
                store_id=service.store_id,
                service_id=service.id,
                name=addon["name"],
                unit_price=Decimal(str(addon["unit_price"])),
                max_quantity=addon["max_quantity"],
                position=position,
            )
            for position, addon in enumerate(addons)
        ]
        self.db.add_all(nuevos)
        await self.db.flush()
        return nuevos
