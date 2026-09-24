"""Imagen de servicio (F1-28, decision 12 del plan de rendimiento).

La imagen se sube a ``store_media`` (``kind='service'``, una por servicio) y
``services.image_url`` pasa a ser la URL servida ``/api/stores/media/{id}``,
la misma que usa el logo. Este service es dueno de su transaccion (CLAUDE.md
§2): el resto del modulo todavia commitea en el repositorio (deuda declarada
en ``tests/architecture/test_boundaries.py``).

Invariante: una URL de medios en ``image_url`` apunta a la imagen de ESE
servicio. Se sube, no se enlaza a mano; y cuando deja de estar enlazada
(reemplazo, baja o PATCH a otra URL) la fila se borra (F1-30).
"""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import ServiceNotFoundException
from modules.services.model import Service
from modules.stores.media import media_url, resolve_image_link
from modules.stores.model import StoreMedia


class ServiceImageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _lock_service(self, public_id: str, store_id: str) -> Service:
        # Lock del servicio antes de tocar su imagen (regla 4): dos subidas a
        # la vez se serializan aca y no chocan contra uq_store_media_service_id.
        result = await self.db.execute(
            select(Service)
            .where(Service.public_id == public_id, Service.store_id == store_id)
            .with_for_update()
        )
        service = result.scalar_one_or_none()
        if service is None:
            raise ServiceNotFoundException(public_id)
        return service

    async def _delete_media_of(self, service: Service) -> None:
        await self.db.execute(
            delete(StoreMedia).where(
                StoreMedia.service_id == service.id,
                StoreMedia.store_id == service.store_id,
            )
        )

    async def upload(
        self,
        public_id: str,
        store_id: str,
        *,
        data: bytes,
        content_type: str,
    ) -> Service:
        """Reemplaza la imagen del servicio. La URL es nueva en cada subida
        (id nuevo): la vieja queda cacheada bajo un id que ya nadie usa."""
        service = await self._lock_service(public_id, store_id)
        await self._delete_media_of(service)
        media = StoreMedia(
            store_id=service.store_id,
            service_id=service.id,
            kind="service",
            content_type=content_type,
            byte_size=len(data),
            data=data,
        )
        self.db.add(media)
        await self.db.flush()
        service.image_url = media_url(media.id)
        await self.db.commit()
        await self.db.refresh(service)
        return service

    async def remove(self, public_id: str, store_id: str) -> Service:
        """Quita la imagen del servicio, subida o externa."""
        service = await self._lock_service(public_id, store_id)
        await self._delete_media_of(service)
        service.image_url = None
        await self.db.commit()
        await self.db.refresh(service)
        return service

    async def apply_image_url_change(
        self, service: Service, changes: dict[str, Any]
    ) -> None:
        """Lo que un PATCH de ``image_url`` le hace a la imagen subida.

        La regla es la del logo (``media.resolve_image_link``): la misma
        imagen por id conserva lo guardado (el front manda el formulario
        entero), otra URL de medios es 422, y cualquier otro cambio borra la
        fila de la imagen que queda sin enlazar (F1-30, decision 21). El
        commit es el del PATCH.
        """
        if "image_url" not in changes:
            return
        guardar, huerfana = resolve_image_link(
            "image_url", service.image_url, changes["image_url"]
        )
        changes["image_url"] = guardar
        if huerfana is not None:
            await self._delete_media_of(service)
