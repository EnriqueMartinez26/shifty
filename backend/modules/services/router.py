from typing import Annotated

from fastapi import Depends, Path, Query, Response, status
from core.router import CanonicalAPIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.exceptions import ServiceNotFoundException
from core.roles import STORE_MANAGERS, require_roles
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_admin
from modules.auth.dependencies import get_current_staff
from modules.services.mappers import to_service_response
from modules.services.repository import ServiceRepository
from modules.services.schemas import ServiceCreate, ServiceResponse, ServiceUpdate
from modules.users.model import User

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
    services = await repo.get_all(user.store_id, only_active=not include_inactive)
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
) -> ServiceResponse:
    repo = ServiceRepository(db)
    service = await repo.get_by_id(public_id, admin.store_id)
    if not service:
        raise ServiceNotFoundException(public_id)
    updated = await repo.update(service, data.model_dump())
    return to_service_response(updated)


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    repo = ServiceRepository(db)
    service = await repo.get_by_id(public_id, admin.store_id)
    if not service:
        raise ServiceNotFoundException(public_id)
    await repo.soft_delete(service)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
