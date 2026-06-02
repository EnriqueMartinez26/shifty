from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import smtplib

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import _apply_tenant_context, get_db, set_tenant_context
from core.rate_limit import enforce_rate_limit
from core.roles import ROLE_SUPER_ADMIN, STORE_MANAGERS, canonical_role, require_roles
from core.security import (
    create_access_token,
    generate_password_reset_token,
    generate_refresh_token,
    hash_password,
    hash_password_reset_token,
    hash_token,
    verify_password,
)
from modules.auth.dependencies import get_current_user
from modules.auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    RegistrationResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    StoreRegisterRequest,
    TokenResponse,
)
from modules.auth.session_model import AuthSession
from modules.stores.model import Store
from modules.users.model import User, UserRole

router = APIRouter(prefix="/auth", tags=["Authentication"])

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"


def _cookie_options() -> dict:
    return {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE.lower(),
        "path": "/",
    }


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **_cookie_options(),
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        **_cookie_options(),
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


def _access_token_for_user(user: User) -> str:
    return create_access_token(
        data={
            "sub": user.public_id,
            "store_id": user.store_id,
            "role": canonical_role(user),
            "is_global_admin": user.is_global_admin,
        }
    )


def _send_password_reset_email(email_to: str, reset_url: str) -> None:
    message = EmailMessage()
    message["Subject"] = "Restablecer contraseña - Shifty"
    message["From"] = settings.EMAILS_FROM_EMAIL
    message["To"] = email_to
    message.set_content(
        "Recibimos una solicitud para restablecer tu contraseña en Shifty. "
        f"Usa este enlace: {reset_url}\n\n"
        f"El enlace vence en {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutos."
    )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
            smtp.send_message(message)
    except Exception:
        return


@router.post("/register", response_model=RegistrationResponse, status_code=status.HTTP_201_CREATED)
async def register_store_and_admin(
    request: Request,
    data: StoreRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    if not settings.ALLOW_PUBLIC_REGISTRATION:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El registro publico no esta habilitado",
        )

    await enforce_rate_limit(
        request,
        "auth:register",
        settings.RATE_LIMIT_AUTH_PER_MINUTE,
        subject=data.admin_email,
    )
    try:
        set_tenant_context(None, True)
        await _apply_tenant_context(db)

        async with db.begin_nested():
            result = await db.execute(select(Store).where(Store.slug == data.store_slug))
            if result.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="El slug de la tienda ya esta en uso")

            result = await db.execute(select(User).where(User.email == data.admin_email))
            if result.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="El email ya esta registrado")

            new_store = Store(
                name=data.store_name,
                slug=data.store_slug,
                theme_config={"business_type": data.business_type},
            )
            db.add(new_store)
            await db.flush()

            new_admin = User(
                email=data.admin_email,
                hashed_password=hash_password(data.admin_password),
                first_name=data.admin_first_name,
                last_name=data.admin_last_name,
                full_name=f"{data.admin_first_name} {data.admin_last_name}".strip(),
                role=UserRole.ADMIN,
                store_id=new_store.id,
            )
            db.add(new_admin)
            await db.flush()

            store_public_id = str(new_store.public_id) if hasattr(new_store, "public_id") else str(new_store.id)
            admin_public_id = str(new_admin.public_id) if hasattr(new_admin, "public_id") else str(new_admin.id)

        await db.commit()

        return {
            "store_public_id": store_public_id,
            "admin": {
                "public_id": admin_public_id,
                "email": new_admin.email,
                "first_name": new_admin.first_name,
                "last_name": new_admin.last_name,
                "role": str(new_admin.role),
            },
        }
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="No se pudo registrar el negocio")
    finally:
        set_tenant_context(None, False)


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limit(
        request,
        "auth:login",
        settings.RATE_LIMIT_AUTH_PER_MINUTE,
        subject=data.email,
    )
    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)

        result = await db.execute(select(User).where(User.email == data.email))
        user = result.scalar_one_or_none()

        if not user or not user.is_active or not verify_password(data.password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")

        access_token = _access_token_for_user(user)
        refresh_token = generate_refresh_token()
        db.add(
            AuthSession(
                user_id=user.id,
                store_id=user.store_id,
                refresh_token_hash=hash_token(refresh_token),
                user_agent=request.headers.get("user-agent"),
                ip_address=request.client.host if request.client else None,
                expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            )
        )
        await db.commit()
        _set_auth_cookies(response, access_token, refresh_token)

        return {"access_token": access_token, "token_type": "bearer"}
    finally:
        set_tenant_context(None, False)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_session(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesion expirada")

    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)
        result = await db.execute(
            select(AuthSession).where(
                AuthSession.refresh_token_hash == hash_token(refresh_token),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > datetime.now(timezone.utc),
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesion expirada")

        user_result = await db.execute(select(User).where(User.id == session.user_id, User.is_active.is_(True)))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesion expirada")

        session.revoked_at = datetime.now(timezone.utc)
        new_refresh_token = generate_refresh_token()
        db.add(
            AuthSession(
                user_id=user.id,
                store_id=user.store_id,
                refresh_token_hash=hash_token(new_refresh_token),
                user_agent=request.headers.get("user-agent"),
                ip_address=request.client.host if request.client else None,
                expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            )
        )
        await db.commit()

        access_token = _access_token_for_user(user)
        _set_auth_cookies(response, access_token, new_refresh_token)
        return {"access_token": access_token, "token_type": "bearer"}
    finally:
        set_tenant_context(None, False)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if refresh_token:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(db)
            result = await db.execute(
                select(AuthSession).where(AuthSession.refresh_token_hash == hash_token(refresh_token))
            )
            session = result.scalar_one_or_none()
            if session and session.revoked_at is None:
                session.revoked_at = datetime.now(timezone.utc)
                await db.commit()
        finally:
            set_tenant_context(None, False)
    _clear_auth_cookies(response)


@router.post("/sessions/revoke-store", status_code=status.HTTP_200_OK)
async def revoke_store_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    require_roles(current_user, STORE_MANAGERS, "Solo administradores pueden revocar sesiones")
    if not current_user.store_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Usuario sin tienda asociada")

    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)
        result = await db.execute(
            select(AuthSession).where(
                AuthSession.store_id == current_user.store_id,
                AuthSession.revoked_at.is_(None),
            )
        )
        now = datetime.now(timezone.utc)
        affected = 0
        for session in result.scalars().all():
            session.revoked_at = now
            affected += 1
        await db.commit()
        return {"revoked_sessions": affected}
    finally:
        set_tenant_context(None, False)


@router.post("/sessions/revoke-user/{user_public_id}", status_code=status.HTTP_200_OK)
async def revoke_user_sessions(
    user_public_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    require_roles(current_user, STORE_MANAGERS, "Solo administradores pueden revocar sesiones")
    if not current_user.store_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Usuario sin tienda asociada")

    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)
        user_result = await db.execute(
            select(User).where(User.id == user_public_id, User.store_id == current_user.store_id)
        )
        target = user_result.scalar_one_or_none()
        if not target:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        sessions_result = await db.execute(
            select(AuthSession).where(AuthSession.user_id == target.id, AuthSession.revoked_at.is_(None))
        )
        now = datetime.now(timezone.utc)
        affected = 0
        for session in sessions_result.scalars().all():
            session.revoked_at = now
            affected += 1
        await db.commit()
        return {"revoked_sessions": affected}
    finally:
        set_tenant_context(None, False)


@router.post("/sessions/revoke-all", status_code=status.HTTP_200_OK)
async def revoke_all_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.is_global_admin and str(current_user.role) != ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operacion exclusiva para superadmin")

    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)
        result = await db.execute(select(AuthSession).where(AuthSession.revoked_at.is_(None)))
        now = datetime.now(timezone.utc)
        affected = 0
        for session in result.scalars().all():
            session.revoked_at = now
            affected += 1
        await db.commit()
        return {"revoked_sessions": affected}
    finally:
        set_tenant_context(None, False)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limit(
        request,
        "auth:forgot-password",
        settings.RATE_LIMIT_AUTH_PER_MINUTE,
        subject=data.email,
    )
    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)

        result = await db.execute(select(User).where(User.email == data.email, User.is_active.is_(True)))
        user = result.scalar_one_or_none()

        if user:
            token = generate_password_reset_token()
            user.password_reset_token_hash = hash_password_reset_token(token)
            user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(
                minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
            )
            await db.commit()

            base_url = settings.FRONTEND_URL.rstrip("/")
            reset_path = settings.FRONTEND_RESET_PASSWORD_PATH
            reset_url = f"{base_url}{reset_path}?token={token}"
            background_tasks.add_task(_send_password_reset_email, user.email, reset_url)

        return {"message": "Si el email existe, recibiras un enlace para restablecer la contraseña."}
    finally:
        set_tenant_context(None, False)


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    request: Request,
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limit(
        request,
        "auth:reset-password",
        settings.RATE_LIMIT_AUTH_PER_MINUTE,
        subject=data.token,
    )
    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)

        token_hash = hash_password_reset_token(data.token)
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(User).where(
                User.password_reset_token_hash == token_hash,
                User.password_reset_expires_at.is_not(None),
                User.password_reset_expires_at >= now,
                User.is_active.is_(True),
            )
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=400, detail="Token invalido o expirado")

        user.hashed_password = hash_password(data.new_password)
        user.password_reset_token_hash = None
        user.password_reset_expires_at = None
        await db.commit()

        return {"message": "Contraseña actualizada correctamente"}
    finally:
        set_tenant_context(None, False)


@router.put("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    request: Request,
    data: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limit(
        request,
        "auth:change-password",
        settings.RATE_LIMIT_AUTH_PER_MINUTE,
        subject=user.public_id,
    )
    if not verify_password(data.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña actual es incorrecta",
        )

    user.hashed_password = hash_password(data.new_password)
    await db.commit()
    return {"message": "Contraseña actualizada correctamente"}
