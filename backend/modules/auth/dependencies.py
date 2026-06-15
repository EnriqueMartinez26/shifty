from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.exceptions import AuthenticationException, PermissionDeniedException
from core.roles import ROLE_SUPER_ADMIN, STORE_MANAGERS, has_any_role
from core.security import decode_token
from modules.users.model import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def _token_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.replace("Bearer ", "", 1)
    return request.cookies.get("access_token")


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    # AI AGENT NOTE: Using structured AppException subclasses instead of raw FastAPI HTTPException
    # to enforce a unified response contract across the entire application.
    credentials_exception = AuthenticationException(
        message="No se pudo validar las credenciales"
    )
    try:
        token = _token_from_request(request)
        if not token:
            raise credentials_exception
        payload = decode_token(token)
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


async def get_optional_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    token = _token_from_request(request)
    if token is None:
        return None
    return await get_current_user(request, db)


async def get_current_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not has_any_role(current_user, STORE_MANAGERS):
        raise PermissionDeniedException("administrador de tienda")
    return current_user


async def get_current_global_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_global_admin and str(current_user.role) != ROLE_SUPER_ADMIN:
        raise PermissionDeniedException("soporte global")
    return current_user
