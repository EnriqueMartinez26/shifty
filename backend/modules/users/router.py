from typing import Annotated

from fastapi import Depends, Path, Query, status
from core.router import CanonicalAPIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppException, UserNotFoundException
from core.database import get_db
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_admin
from modules.users.model import User
from modules.users.repository import UserRepository
from modules.users.schemas import UserCreate, UserResponse, UserUpdate

router = CanonicalAPIRouter(prefix="/users", tags=["Users Management"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = UserRepository(db)
    try:
        return await repo.create(data.model_dump(), admin.store_id)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.get("/", response_model=list[UserResponse])
async def list_users(
    include_inactive: bool = Query(False),
    email: str | None = Query(None, max_length=255),
    role: str | None = Query(None, max_length=50),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = UserRepository(db)
    return await repo.get_all(
        admin.store_id,
        only_active=not include_inactive,
        email=email,
        role=role,
    )


@router.get("/{public_id}", response_model=UserResponse)
async def get_user(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = UserRepository(db)
    user = await repo.get_by_public_id(public_id, admin.store_id)
    if not user:
        raise UserNotFoundException(public_id)
    return user


@router.patch("/{public_id}", response_model=UserResponse)
async def update_user(
    public_id: PublicIdPath,
    data: UserUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = UserRepository(db)
    user = await repo.get_by_public_id(public_id, admin.store_id)
    if not user:
        raise UserNotFoundException(public_id)

    try:
        return await repo.update(user, data.model_dump())
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    if admin.public_id == public_id:
        raise AppException(
            message="No podés desactivar tu propio usuario",
            http_status=400,
            error_code="SELF_DEACTIVATION_DENIED",
        )

    repo = UserRepository(db)
    user = await repo.get_by_public_id(public_id, admin.store_id)
    if not user:
        raise UserNotFoundException(public_id)

    await repo.soft_delete(user)
