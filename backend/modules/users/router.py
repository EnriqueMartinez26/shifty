from typing import Annotated

from fastapi import Depends, Path, Query, Response, status
from core.router import CanonicalAPIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppException, UserNotFoundException, ValidationException
from core.database import get_db
from core.roles import (
    assert_can_change_access,
    assert_can_grant_role,
    assert_global_admin_keeps_login_role,
)
from modules.users.guards import assert_deactivation_allowed
from core.validation import PUBLIC_ID_PATTERN, reject_control_chars
from modules.auth.dependencies import get_current_admin
from modules.users.model import User
from modules.users.repository import UserRepository
from modules.users.schemas import UserCreate, UserResponse, UserUpdate
from modules.users.service import UserService

router = CanonicalAPIRouter(prefix="/users", tags=["Users Management"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    # Regla 16: un admin de tienda no da de alta a otro admin (B3-02).
    assert_can_grant_role(admin, data.role)
    try:
        return UserResponse.model_validate(
            await UserService(db).create(data.model_dump(), admin.store_id)
        )
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.get("/", response_model=list[UserResponse])
async def list_users(
    include_inactive: bool = Query(False),
    email: str | None = Query(None, max_length=255),
    role: str | None = Query(None, max_length=50),
    # FF-20 / F4-03 (aditivo): nombre que contiene q o digitos del telefono.
    q: str | None = Query(None, min_length=2, max_length=80),
    limit: int = Query(200, ge=1, le=500),
    # Tope superior: sin el, un offset por encima del bigint de Postgres
    # (2^63-1) desbordaba la query y salia 500. Un millon ya es absurdo para
    # el listado de una tienda.
    offset: int = Query(0, ge=0, le=1_000_000),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[UserResponse]:
    try:
        reject_control_chars(q)
    except ValueError as exc:
        raise ValidationException(str(exc)) from None
    repo = UserRepository(db)
    users = await repo.get_all(
        admin.store_id,
        only_active=not include_inactive,
        email=email,
        role=role,
        limit=limit,
        offset=offset,
        include_global_admins=admin.is_global_admin,
        q=q,
    )
    return [UserResponse.model_validate(user) for user in users]


@router.get("/{public_id}", response_model=UserResponse)
async def get_user(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    repo = UserRepository(db)
    user = await repo.get_by_public_id(
        public_id, admin.store_id, include_global_admins=admin.is_global_admin
    )
    if not user:
        raise UserNotFoundException(public_id)
    return UserResponse.model_validate(user)


@router.patch("/{public_id}", response_model=UserResponse)
async def update_user(
    public_id: PublicIdPath,
    data: UserUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    # La propia contraseña se cambia SOLO por /auth/change-password, que exige
    # la actual: sin este bloqueo, una sesion secuestrada podia fijarse una
    # clave nueva sin conocer la anterior.
    if admin.public_id == public_id and data.password is not None:
        raise AppException(
            message="Para cambiar tu propia contraseña usá /auth/change-password",
            http_status=400,
            error_code="SELF_PASSWORD_CHANGE_DENIED",
        )

    repo = UserRepository(db)
    user = await repo.get_by_public_id(
        public_id, admin.store_id, include_global_admins=admin.is_global_admin
    )
    if not user:
        raise UserNotFoundException(public_id)
    # Regla 16: un admin de tienda no asciende a nadie a admin (B3-02).
    assert_can_grant_role(admin, data.role, current=user.role)
    # S-15: ni clave, ni estado, ni rol de OTRO admin de tienda.
    assert_can_change_access(
        admin, user, password=data.password, is_active=data.is_active, role=data.role
    )
    # PV-01: un superadmin con rol de cliente quedaba afuera del login.
    assert_global_admin_keeps_login_role(user, data.role)
    # Regla 14: tambien por aca se llegaba a dejar la plataforma sin SuperAdmin
    # activo (AUD2-B3-01).
    await assert_deactivation_allowed(db, admin, user, is_active=data.is_active)

    try:
        # ``exclude_unset``: sin el, "no vino" y "vino null" llegan iguales al
        # repositorio y el PATCH no puede borrar un campo (AUD2-B3-08).
        return UserResponse.model_validate(
            await UserService(db).update(user, data.model_dump(exclude_unset=True))
        )
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if admin.public_id == public_id:
        raise AppException(
            message="No podés desactivar tu propio usuario",
            http_status=400,
            error_code="SELF_DEACTIVATION_DENIED",
        )

    repo = UserRepository(db)
    user = await repo.get_by_public_id(
        public_id, admin.store_id, include_global_admins=admin.is_global_admin
    )
    if not user:
        raise UserNotFoundException(public_id)
    # La baja es un cambio de estado: tampoco sobre OTRO admin de tienda (S-15).
    assert_can_change_access(admin, user, is_active=False)
    await assert_deactivation_allowed(db, admin, user, is_active=False)

    await UserService(db).soft_delete(user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
