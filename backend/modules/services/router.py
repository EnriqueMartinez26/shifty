from typing import Annotated

from fastapi import Depends, File, Path, Query, Response, UploadFile, status
from core.router import CanonicalAPIRouter
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.exceptions import ServiceNotFoundException
from core.redis import get_availability_cache
from core.roles import STORE_MANAGERS, require_roles
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_admin
from modules.auth.dependencies import get_current_staff
from modules.services.mappers import to_service_responses
from modules.services.model import Service
from modules.services.repository import ServiceRepository
from modules.services.schemas import (
    ServiceCreate,
    ServiceCatalogResponse,
    ServiceUpdate,
)
from modules.services.service import ServiceCatalogService, ServiceImageService
from modules.stores.media import IMAGE_CAPS, prepare_image
from modules.users.model import User

router = CanonicalAPIRouter(prefix="/services", tags=["Services"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


async def _respuesta(
    db: AsyncSession, store_id: str, service: Service
) -> ServiceCatalogResponse:
    """Un servicio con sus adicionales (``to_service_responses``)."""
    (respuesta,) = await to_service_responses(
        ServiceRepository(db), store_id, [service]
    )
    return respuesta


@router.post(
    "/", response_model=ServiceCatalogResponse, status_code=status.HTTP_201_CREATED
)
async def create_service(
    data: ServiceCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ServiceCatalogResponse:
    service = await ServiceCatalogService(db).create(data.model_dump(), admin.store_id)
    return await _respuesta(db, admin.store_id, service)


@router.get("/", response_model=list[ServiceCatalogResponse])
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
) -> list[ServiceCatalogResponse]:
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
    return await to_service_responses(repo, user.store_id, services)


@router.get("/{public_id}", response_model=ServiceCatalogResponse)
async def get_service(
    public_id: PublicIdPath,
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> ServiceCatalogResponse:
    repo = ServiceRepository(db)
    service = await repo.get_by_id(public_id, user.store_id)
    if not service:
        raise ServiceNotFoundException(public_id)
    return await _respuesta(db, user.store_id, service)


@router.patch("/{public_id}", response_model=ServiceCatalogResponse)
async def update_service(
    public_id: PublicIdPath,
    data: ServiceUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    availability_cache: Redis = Depends(get_availability_cache),
) -> ServiceCatalogResponse:
    # B6-04: solo los campos enviados; un null explicito borra el opcional.
    changes = data.model_dump(exclude_unset=True)
    if data.addons is not None:
        # Cada adicional completo (con sus defaults): ``exclude_unset`` llega
        # tambien a los modelos anidados.
        changes["addons"] = [addon.model_dump() for addon in data.addons]
    updated = await ServiceCatalogService(db, availability_cache).update(
        public_id, admin.store_id, changes
    )
    return await _respuesta(db, admin.store_id, updated)


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    availability_cache: Redis = Depends(get_availability_cache),
) -> Response:
    await ServiceCatalogService(db, availability_cache).soft_delete(
        public_id, admin.store_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{public_id}/image", response_model=ServiceCatalogResponse)
async def upload_service_image(
    public_id: PublicIdPath,
    file: UploadFile = File(...),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ServiceCatalogResponse:
    """Sube (o reemplaza) la imagen del servicio (F1-28).

    Multipart con el campo ``file``; mismos controles que el logo con el tope
    de servicio (1600 px por lado, 1 MB). ``image_url`` queda en la URL
    servida ``/api/stores/media/{id}``, que cambia en cada subida.
    """
    # Se leen a lo sumo tope+1 bytes: "se paso" sin cargar un blob gigante.
    data = await file.read(IMAGE_CAPS["service"].max_bytes + 1)
    # Un JPEG se guarda sin Exif/XMP (PV-15).
    data, content_type = prepare_image(data, "service")
    service = await ServiceImageService(db).upload(
        public_id, admin.store_id, data=data, content_type=content_type
    )
    return await _respuesta(db, admin.store_id, service)


@router.delete("/{public_id}/image", response_model=ServiceCatalogResponse)
async def delete_service_image(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ServiceCatalogResponse:
    """Quita la imagen del servicio (subida o URL externa) y borra la fila."""
    service = await ServiceImageService(db).remove(public_id, admin.store_id)
    return await _respuesta(db, admin.store_id, service)
