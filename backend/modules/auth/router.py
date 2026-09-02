from typing import Annotated, Any

from fastapi import (
    BackgroundTasks,
    Depends,
    Path,
    Request,
    Response,
    status,
)

from core.router import CanonicalAPIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.validation import PUBLIC_ID_PATTERN
from core.database import get_db
from core.rate_limit import enforce_rate_limit
from modules.auth.dependencies import get_current_user
from modules.auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LogoutRequest,
    RegistrationResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SessionItem,
    SessionListResponse,
    StoreRegisterRequest,
    TokenResponse,
)
from modules.auth.service import (
    RevokedSessionsResult,
    SessionClientContext,
    change_password as change_password_service,
    login_user,
    logout_session,
    normalize_email,
    refresh_session as refresh_session_service,
    register_store_and_admin as register_store_and_admin_service,
    request_password_reset,
    reset_password as reset_password_service,
    revoke_all_sessions as revoke_all_sessions_service,
    revoke_store_sessions as revoke_store_sessions_service,
    revoke_user_sessions as revoke_user_sessions_service,
    list_user_sessions as list_user_sessions_service,
    revoke_own_session as revoke_own_session_service,
    send_password_changed_email,
    send_password_reset_email,
)
from modules.users.model import User

router = CanonicalAPIRouter(prefix="/auth", tags=["Authentication"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"


def _cookie_options() -> dict[str, Any]:
    return {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE.lower(),
        "path": "/",
    }


def _set_auth_cookies(response: Response, refresh_token: str) -> None:
    # Solo el refresh viaja en cookie (HttpOnly). El access token va en el body
    # y se usa via header Authorization: la cookie de access dejo de aceptarse
    # como credencial para cortar el CSRF, asi que setearla era solo superficie.
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        **_cookie_options(),
    )


def _clear_auth_cookies(response: Response) -> None:
    # delete_cookie debe replicar los atributos del set: con SameSite/secure
    # distintos algunos navegadores lo tratan como una cookie diferente.
    response.delete_cookie(ACCESS_COOKIE, **_cookie_options())
    response.delete_cookie(REFRESH_COOKIE, **_cookie_options())


def _session_context(request: Request) -> SessionClientContext:
    return SessionClientContext(
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


@router.post(
    "/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_store_and_admin(
    request: Request,
    data: StoreRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> RegistrationResponse:
    admin_email = normalize_email(str(data.admin_email))
    await enforce_rate_limit(
        request,
        "auth:register",
        settings.RATE_LIMIT_AUTH_PER_MINUTE,
        subject=admin_email,
    )
    result = await register_store_and_admin_service(data, db)
    return RegistrationResponse.model_validate(result)


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    normalized_email = normalize_email(str(data.email))
    await enforce_rate_limit(
        request,
        "auth:login",
        settings.RATE_LIMIT_AUTH_PER_MINUTE,
        subject=normalized_email,
    )
    tokens = await login_user(data.email, data.password, db, _session_context(request))
    _set_auth_cookies(response, tokens.refresh_token)
    return TokenResponse(access_token=tokens.access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_session(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    tokens = await refresh_session_service(
        request.cookies.get(REFRESH_COOKIE), db, _session_context(request)
    )
    _set_auth_cookies(response, tokens.refresh_token)
    return TokenResponse(access_token=tokens.access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    data: LogoutRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> None:
    # Cookie (navegador) o body (cliente movil/CLI que guardo el refresh).
    refresh_token = request.cookies.get(REFRESH_COOKIE) or (
        data.refresh_token if data else None
    )
    await logout_session(refresh_token, db)
    _clear_auth_cookies(response)


@router.get("/sessions", response_model=SessionListResponse)
async def list_my_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionListResponse:
    """Las sesiones abiertas del propio usuario, para detectar accesos ajenos."""
    sessions = await list_user_sessions_service(
        current_user, db, request.cookies.get(REFRESH_COOKIE)
    )
    return SessionListResponse(
        sessions=[
            SessionItem(
                session_id=session.id,
                created_at=session.created_at.isoformat(),
                expires_at=session.expires_at.isoformat(),
                user_agent=session.user_agent,
                ip_address=session.ip_address,
                current=is_current,
            )
            for session, is_current in sessions
        ]
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_session(
    session_id: PublicIdPath,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await revoke_own_session_service(session_id, current_user, db)


@router.post("/sessions/revoke-store", status_code=status.HTTP_200_OK)
async def revoke_store_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RevokedSessionsResult:
    return await revoke_store_sessions_service(current_user, db)


@router.post("/sessions/revoke-user/{user_public_id}", status_code=status.HTTP_200_OK)
async def revoke_user_sessions(
    user_public_id: PublicIdPath,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RevokedSessionsResult:
    return await revoke_user_sessions_service(user_public_id, current_user, db)


@router.post("/sessions/revoke-all", status_code=status.HTTP_200_OK)
async def revoke_all_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RevokedSessionsResult:
    return await revoke_all_sessions_service(current_user, db)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> ForgotPasswordResponse:
    normalized_email = normalize_email(str(data.email))
    await enforce_rate_limit(
        request,
        "auth:forgot-password",
        settings.RATE_LIMIT_AUTH_PER_MINUTE,
        subject=normalized_email,
    )
    reset_email = await request_password_reset(data, db)
    if reset_email:
        background_tasks.add_task(
            send_password_reset_email, reset_email.email_to, reset_email.reset_url
        )
    return ForgotPasswordResponse(
        message="Si el email existe, recibiras un enlace para restablecer la contraseña."
    )


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    request: Request,
    data: ResetPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> ResetPasswordResponse:
    await enforce_rate_limit(
        request,
        "auth:reset-password",
        settings.RATE_LIMIT_AUTH_PER_MINUTE,
    )
    outcome = await reset_password_service(data, db)
    background_tasks.add_task(send_password_changed_email, outcome.email_to)
    return ResetPasswordResponse(message=outcome.message)


@router.put("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    request: Request,
    data: ChangePasswordRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResetPasswordResponse:
    await enforce_rate_limit(
        request,
        "auth:change-password",
        settings.RATE_LIMIT_AUTH_PER_MINUTE,
        subject=user.public_id,
    )
    result = await change_password_service(
        data,
        user,
        db,
        preserve_refresh_token=request.cookies.get(REFRESH_COOKIE),
    )
    background_tasks.add_task(send_password_changed_email, user.email)
    return ResetPasswordResponse.model_validate(result)
