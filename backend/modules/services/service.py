"""Imagen de servicio (F1-28, decision 12 del plan de rendimiento).

La imagen se sube a ``store_media`` (``kind='service'``, una por servicio) y
``services.image_url`` pasa a ser la URL servida ``/api/stores/media/{id}``,
la misma que usa el logo. Los dos services de este archivo son duenos de la
transaccion del modulo (CLAUDE.md §2): ``ServiceCatalogService`` el alta, el
PATCH y la baja del catalogo, ``ServiceImageService`` la imagen. El
repositorio solo hace ``flush`` (B6-05, 2026-09-30).

Invariante: una URL de medios en ``image_url`` apunta a la imagen de ESE
servicio. Se sube, no se enlaza a mano; y cuando deja de estar enlazada
(reemplazo, baja o PATCH a otra URL) la fila se borra (F1-30).
"""

from typing import Any

import structlog
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.availability_cache import (
    AvailabilityCacheClient,
    invalidate_store_availability,
)
from core.exceptions import ServiceNotFoundException, ValidationException
from modules.services.model import Service
from modules.services.repository import ServiceRepository
from modules.services.schemas import DEPOSIT_FIELDS, deposit_policy_error
from modules.stores.media import media_url, resolve_image_link
from modules.stores.model import StoreMedia

logger = structlog.get_logger()


def _validate_deposit_patch(service: Service, changes: dict[str, Any]) -> None:
    """B6-02: el PATCH es parcial, asi que la terna se valida contra la fila.

    Solo si el PATCH toca la sena: un servicio viejo con una terna invalida
    sigue pudiendo cambiar de nombre o de precio.
    """
    if not any(field in changes for field in DEPOSIT_FIELDS):
        return
    merged = {
        field: changes.get(field, getattr(service, field)) for field in DEPOSIT_FIELDS
    }
    amount = merged["deposit_amount"]
    error = deposit_policy_error(
        str(merged["deposit_mode"]),
        str(merged["deposit_type"]),
        None if amount is None else float(amount),
    )
    if error:
        raise ValidationException(error)


class ServiceCatalogService:
    """Alta, edicion y baja del catalogo: dueno de la transaccion (B6-05).

    El PATCH de ``image_url`` borra en la MISMA transaccion la fila de la
    imagen subida que queda sin enlazar (F1-30): es una fila de ``store_media``,
    no un archivo, asi que no hay efecto externo que ordenar y un fallo del
    commit deja servicio e imagen como estaban. El unico efecto de afuera es la
    invalidacion del cache de disponibilidad (un servicio cambia la grilla de
    todos los dias, B6-08): va DESPUES del commit y es best-effort, un Redis
    caido no revierte lo ya guardado; en el peor caso el portal muestra lo
    viejo hasta que vencen los slots (``SLOTS_TTL_SECONDS``, 300 s).
    """

    def __init__(
        self, db: AsyncSession, cache: AvailabilityCacheClient | None = None
    ) -> None:
        self.db = db
        self.repo = ServiceRepository(db)
        self.images = ServiceImageService(db)
        self.cache = cache

    async def _invalidar_disponibilidad(self, store_id: str) -> None:
        if self.cache is None:
            return
        try:
            await invalidate_store_availability(self.cache, store_id)
        except RedisError as exc:
            logger.warning(
                "service_cache_invalidation_failed",
                store_id=store_id,
                error_type=type(exc).__name__,
            )

    async def create(self, service_data: dict[str, Any], store_id: str) -> Service:
        service = await self.repo.create(service_data, store_id)
        await self.db.commit()
        return service

    async def update(
        self, public_id: str, store_id: str, changes: dict[str, Any]
    ) -> Service:
        service = await self.repo.get_by_id(public_id, store_id)
        if not service:
            raise ServiceNotFoundException(public_id)
        _validate_deposit_patch(service, changes)
        await self.images.apply_image_url_change(service, changes)
        updated = await self.repo.update(service, changes)
        await self.db.commit()
        await self._invalidar_disponibilidad(str(updated.store_id))
        return updated

    async def soft_delete(self, public_id: str, store_id: str) -> None:
        service = await self.repo.get_by_id(public_id, store_id)
        if not service:
            raise ServiceNotFoundException(public_id)
        await self.repo.soft_delete(service)
        await self.db.commit()
        await self._invalidar_disponibilidad(str(service.store_id))


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
