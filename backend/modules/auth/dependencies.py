from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import _apply_tenant_context, get_db, set_tenant_context
from core.exceptions import AuthenticationException, PermissionDeniedException
from core.roles import ROLE_SUPER_ADMIN, STORE_MANAGERS, has_any_role
from core.security import decode_token
from modules.auth.session_model import AuthSession
from modules.users.model import User


def _aware(value: datetime) -> datetime:
    """SQLite devuelve naive aun con DateTime(timezone=True); Postgres, aware."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def _token_from_request(request: Request) -> str | None:
    """SOLO el header Authorization.

    La cookie ``access_token`` ya no es credencial: aceptarla convertia a cada
    endpoint de escritura en un blanco de CSRF (la cookie viaja sola en
    requests cross-site). La cookie de refresh se lee unicamente en
    /auth/refresh, de forma explicita.
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.replace("Bearer ", "", 1)
    return None


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Autentica el request y establece el contexto RLS desde la BASE.

    Dos decisiones de seguridad deliberadas:

    - El contexto de tenant (``store_id`` / ``is_global_admin``) sale del
      usuario recien leido de la DB, nunca de los claims del token. Revocar el
      flag de superadmin o desactivar al usuario surte efecto en el proximo
      request, y un token forjado sin usuario real no obtiene contexto.
    - El token esta atado a una sesion del servidor (claim ``sid``): si la
      sesion fue revocada (logout, cambio de password, boton de panico), el
      access token muere con ella en vez de sobrevivir hasta su exp.
    """
    credentials_exception = AuthenticationException(
        message="No se pudo validar las credenciales"
    )
    try:
        token = _token_from_request(request)
        if not token:
            raise credentials_exception
        payload = decode_token(token)
        user_id = payload.get("sub")
        session_id = payload.get("sid")
        if not isinstance(user_id, str) or not isinstance(session_id, str):
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Bypass acotado SOLO para resolver la identidad: las tablas users y
    # auth_sessions tienen RLS por tienda y todavia no sabemos la tienda.
    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)

        session_result = await db.execute(
            select(AuthSession).where(AuthSession.id == session_id)
        )
        session = session_result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if (
            session is None
            or session.revoked_at is not None
            or _aware(session.expires_at) <= now
        ):
            raise credentials_exception

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None or not user.is_active or session.user_id != user.id:
            raise credentials_exception
    except Exception:
        # Camino de error: el request sigue sin ningun privilegio.
        set_tenant_context(None, False)
        await _apply_tenant_context(db)
        raise

    # Exito: el contexto REAL del request es lo que dice la base para este
    # usuario — no lo que diga el token.
    set_tenant_context(user.store_id, user.is_global_admin)
    await _apply_tenant_context(db)
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
