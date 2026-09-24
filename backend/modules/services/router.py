from typing import Annotated, Any

import structlog
from fastapi import Depends, File, Path, Query, Response, UploadFile, status
from core.router import CanonicalAPIRouter
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from core.availability_cache import invalidate_store_availability
from core.database import get_db
from core.exceptions import ServiceNotFoundException, ValidationException
from core.redis import get_availability_cache
from core.roles import STORE_MANAGERS, require_roles
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_admin
from modules.auth.dependencies import get_current_staff
from modules.services.mappers import to_service_response
from modules.services.model import Service
from modules.services.repository import ServiceRepository
from modules.services.schemas import (
    DEPOSIT_FIELDS,
    ServiceCreate,
    ServiceResponse,
    ServiceUpdate,
    deposit_policy_error,
)
from modules.services.service import ServiceImageService
from modules.stores.media import IMAGE_CAPS, validate_image
from modules.users.model import User

logger = structlog.get_logger()
router = CanonicalAPIRouter(prefix="/services", tags=["Services"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


@router.post("/", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
async def create_service(
    data: ServiceCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ServiceResponse:
    repo = ServiceRepository(db)
    service = await repo.create(data.model_dump(), admin.store_id)
    return to_service_response(service)


@router.get("/", response_model=list[ServiceResponse])
async def list_services(
    # B6-06: sin esto un servicio borrado (soft delete) no se podia enumerar
    # para reactivarlo. Default False = la respuesta de siempre (el front no
    # lo manda). Ver inactivos es gestion del catalogo: mismos roles que
    # borran/reactivan.
    include_inactive: bool = Query(False),
    # B6-10: mismas cotas que users/router.py (regla 9: ge Y le). El default
    # es el techo (500) para que la respuesta sin parametros siga siendo la
    # lista completa del catalogo de cualquier tienda real; el front no los
    # manda.
    limit: int = Query(500, ge=1, le=500),
    offset: int = Query(0, ge=0, le=1_000_000),
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> list[ServiceResponse]:
    if include_inactive:
        require_roles(
            user,
            STORE_MANAGERS,
            "Solo un administrador de tienda ve servicios inactivos",
        )
    repo = ServiceRepository(db)
    services = await repo.get_all(
        user.store_id,
        only_active=not include_inactive,
        limit=limit,
        offset=offset,
    )
    return [to_service_response(service) for service in services]


@router.get("/{public_id}", response_model=ServiceResponse)
async def get_service(
    public_id: PublicIdPath,
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> ServiceResponse:
    repo = ServiceRepository(db)
    service = await repo.get_by_id(public_id, user.store_id)
    if not service:
        raise ServiceNotFoundException(public_id)
    return to_service_response(service)


@router.patch("/{public_id}", response_model=ServiceResponse)
async def update_service(
    public_id: PublicIdPath,
    data: ServiceUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    availability_cache: Redis = Depends(get_availability_cache),
) -> ServiceResponse:
    repo = ServiceRepository(db)
    service = await repo.get_by_id(public_id, admin.store_id)
    if not service:
        raise ServiceNotFoundException(public_id)
    # B6-04: solo los campos enviados; un null explicito borra el opcional.
    changes = data.model_dump(exclude_unset=True)
    _validate_deposit_patch(service, changes)
    ServiceImageService(db).check_image_url_change(service, changes)
    updated = await repo.update(service, changes)
    await _invalidate_store_cache(availability_cache, str(updated.store_id))
    return to_service_response(updated)


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


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    availability_cache: Redis = Depends(get_availability_cache),
) -> Response:
    repo = ServiceRepository(db)
    service = await repo.get_by_id(public_id, admin.store_id)
    if not service:
        raise ServiceNotFoundException(public_id)
    await repo.soft_delete(service)
    await _invalidate_store_cache(availability_cache, str(service.store_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{public_id}/image", response_model=ServiceResponse)
async def upload_service_image(
    public_id: PublicIdPath,
    file: UploadFile = File(...),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ServiceResponse:
    """Sube (o reemplaza) la imagen del servicio (F1-28).

    Multipart con el campo ``file``; mismos controles que el logo con el tope
    de servicio (1600 px por lado, 1 MB). ``image_url`` queda en la URL
    servida ``/api/stores/media/{id}``, que cambia en cada subida.
    """
    # Se leen a lo sumo tope+1 bytes: "se paso" sin cargar un blob gigante.
    data = await file.read(IMAGE_CAPS["service"].max_bytes + 1)
    content_type = validate_image(data, "service")
    service = await ServiceImageService(db).upload(
        public_id, admin.store_id, data=data, content_type=content_type
    )
    return to_service_response(service)


@router.delete("/{public_id}/image", response_model=ServiceResponse)
async def delete_service_image(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ServiceResponse:
    """Quita la imagen del servicio (subida o URL externa) y borra la fila."""
    service = await ServiceImageService(db).remove(public_id, admin.store_id)
    return to_service_response(service)


async def _invalidate_store_cache(redis: Redis, store_id: str) -> None:
    """B6-08: un servicio cambia la disponibilidad de todos los dias.

    Va despues del commit (el repo ya commiteo). Best-effort: un Redis caido
    no rompe la edicion ya guardada; en el peor caso la pagina publica
    muestra lo viejo hasta el TTL de los slots (300 s).
    """
    try:
        await invalidate_store_availability(redis, store_id)
    except RedisError as exc:
        logger.warning(
            "service_cache_invalidation_failed",
            store_id=store_id,
            error_type=type(exc).__name__,
        )
