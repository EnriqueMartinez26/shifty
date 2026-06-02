from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_admin, get_current_user
from modules.users.model import User
from modules.services.schemas import ServiceCreate, ServiceUpdate, ServiceResponse
from modules.services.repository import ServiceRepository

router = APIRouter(prefix="/services", tags=["Services"])
PublicIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)]

@router.post("/", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
async def create_service(
    data: ServiceCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Crea un nuevo servicio (Sólo Administradores)."""
    repo = ServiceRepository(db)
    return await repo.create(data.model_dump(), admin.store_id)

@router.get("/", response_model=list[ServiceResponse])
async def list_services(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lista servicios disponibles para el usuario logueado."""
    repo = ServiceRepository(db)
    return await repo.get_all(user.store_id)

@router.get("/{public_id}", response_model=ServiceResponse)
async def get_service(
    public_id: PublicIdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Obtiene detalles de un servicio específico."""
    repo = ServiceRepository(db)
    service = await repo.get_by_id(public_id)
    if not service:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    return service

@router.patch("/{public_id}", response_model=ServiceResponse)
async def update_service(
    public_id: PublicIdPath,
    data: ServiceUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Actualiza un servicio (Sólo Administradores)."""
    repo = ServiceRepository(db)
    service = await repo.get_by_id(public_id)
    if not service:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    
    return await repo.update(service, data.model_dump())


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = ServiceRepository(db)
    service = await repo.get_by_id(public_id)
    if not service:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    await repo.soft_delete(service)
