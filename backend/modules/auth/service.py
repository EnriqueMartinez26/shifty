from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import secrets
import smtplib
from typing import TypedDict

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import _apply_tenant_context, set_tenant_context
from core.exceptions import (
    AppException,
    AuthenticationException,
    DuplicateAccountException,
    InvalidTokenException,
    PermissionDeniedException,
    RegistrationDisabledException,
    UserNotFoundException,
)
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
from modules.auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    StoreRegisterRequest,
)
from modules.auth.session_model import AuthSession
from modules.stores.model import Store
from modules.users.model import User, UserRole

__all__ = [
    "AuthTokenPair",
    "MessageResult",
    "PasswordResetEmail",
    "RegistrationAdminResult",
    "RegistrationResult",
    "RevokedSessionsResult",
    "SessionClientContext",
    "access_token_for_user",
    "change_password",
    "hash_password_reset_token",
    "hash_token",
    "login_user",
    "logout_session",
    "normalize_email",
    "refresh_session",
    "register_store_and_admin",
    "request_password_reset",
    "reset_password",
    "revoke_all_sessions",
    "revoke_store_sessions",
    "revoke_user_sessions",
    "send_password_reset_email",
    "settings",
]


class RegistrationAdminResult(TypedDict):
    public_id: str
    email: str
    first_name: str | None
    last_name: str | None
    role: str


class RegistrationResult(TypedDict):
    store_public_id: str
    admin: RegistrationAdminResult


class RevokedSessionsResult(TypedDict):
    revoked_sessions: int


class MessageResult(TypedDict):
    message: str


@dataclass(frozen=True)
class SessionClientContext:
    user_agent: str | None = None
    ip_address: str | None = None


@dataclass(frozen=True)
class AuthTokenPair:
    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class PasswordResetEmail:
    email_to: str
    reset_url: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


# Hash de sacrificio para igualar el tiempo de respuesta cuando el email no
# existe. Sin esto, la diferencia entre "no hay usuario" (respuesta rapida) y
# "password incorrecta" (bcrypt lento) permite enumerar cuentas por timing.
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(24))


def access_token_for_user(user: User) -> str:
    return create_access_token(
        data={
            "sub": user.public_id,
            "store_id": user.store_id,
            "role": canonical_role(user),
            "is_global_admin": user.is_global_admin,
        }
    )


def send_password_reset_email(email_to: str, reset_url: str) -> None:
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


def _new_auth_session(
    user: User, refresh_token: str, context: SessionClientContext
) -> AuthSession:
    return AuthSession(
        user_id=user.id,
        store_id=user.store_id,
        refresh_token_hash=hash_token(refresh_token),
        user_agent=context.user_agent,
        ip_address=context.ip_address,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


async def register_store_and_admin(
    data: StoreRegisterRequest, db: AsyncSession
) -> RegistrationResult:
    admin_email = normalize_email(str(data.admin_email))
    if not settings.ALLOW_PUBLIC_REGISTRATION:
        raise RegistrationDisabledException()

    try:
        set_tenant_context(None, True)
        await _apply_tenant_context(db)

        async with db.begin_nested():
            result = await db.execute(
                select(Store).where(Store.slug == data.store_slug)
            )
            if result.scalar_one_or_none():
                raise AppException(
                    message="El slug de la tienda ya esta en uso",
                    http_status=400,
                    error_code="DUPLICATE_STORE_SLUG",
                )

            result = await db.execute(
                select(User).where(func.lower(User.email) == admin_email)
            )
            if result.scalar_one_or_none():
                raise DuplicateAccountException(field="email")

            new_store = Store(
                name=data.store_name,
                slug=data.store_slug,
                theme_config={"business_type": data.business_type},
            )
            new_store.public_id = new_store.id
            db.add(new_store)
            await db.flush()

            new_admin = User(
                email=admin_email,
                hashed_password=hash_password(data.admin_password),
                first_name=data.admin_first_name,
                last_name=data.admin_last_name,
                full_name=f"{data.admin_first_name} {data.admin_last_name}".strip(),
                role=UserRole.ADMIN,
                store_id=new_store.id,
            )
            db.add(new_admin)
            await db.flush()

            store_public_id = (
                str(new_store.public_id)
                if hasattr(new_store, "public_id")
                else str(new_store.id)
            )
            admin_public_id = (
                str(new_admin.public_id)
                if hasattr(new_admin, "public_id")
                else str(new_admin.id)
            )

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
    except AppException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise AppException(
            message="No se pudo registrar el negocio",
            http_status=500,
            error_code="REGISTRATION_FAILED",
        )
    finally:
        set_tenant_context(None, False)


async def login_user(
    email: str, password: str, db: AsyncSession, context: SessionClientContext
) -> AuthTokenPair:
    normalized_email = normalize_email(email)
    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)

        result = await db.execute(
            select(User).where(func.lower(User.email) == normalized_email)
        )
        user = result.scalar_one_or_none()

        # Se verifica SIEMPRE una password (real o de sacrificio) para que el
        # tiempo de respuesta no revele si el email existe.
        hashed = user.hashed_password if user else _DUMMY_PASSWORD_HASH
        password_ok = verify_password(password, hashed)
        if not user or not user.is_active or not password_ok:
            raise AuthenticationException(message="Credenciales incorrectas")

        access_token = access_token_for_user(user)
        refresh_token = generate_refresh_token()
        db.add(_new_auth_session(user, refresh_token, context))
        await db.commit()
        return AuthTokenPair(access_token=access_token, refresh_token=refresh_token)
    finally:
        set_tenant_context(None, False)


async def refresh_session(
    refresh_token: str | None, db: AsyncSession, context: SessionClientContext
) -> AuthTokenPair:
    if not refresh_token:
        raise AuthenticationException(message="Sesion expirada")

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
            raise AuthenticationException(message="Sesion expirada")

        user_result = await db.execute(
            select(User).where(User.id == session.user_id, User.is_active.is_(True))
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise AuthenticationException(message="Sesion expirada")

        session.revoked_at = datetime.now(timezone.utc)
        new_refresh_token = generate_refresh_token()
        db.add(_new_auth_session(user, new_refresh_token, context))
        await db.commit()

        return AuthTokenPair(
            access_token=access_token_for_user(user), refresh_token=new_refresh_token
        )
    finally:
        set_tenant_context(None, False)


async def logout_session(refresh_token: str | None, db: AsyncSession) -> None:
    if not refresh_token:
        return

    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)
        result = await db.execute(
            select(AuthSession).where(
                AuthSession.refresh_token_hash == hash_token(refresh_token)
            )
        )
        session = result.scalar_one_or_none()
        if session and session.revoked_at is None:
            session.revoked_at = datetime.now(timezone.utc)
            await db.commit()
    finally:
        set_tenant_context(None, False)


async def revoke_store_sessions(
    current_user: User, db: AsyncSession
) -> RevokedSessionsResult:
    require_roles(
        current_user, STORE_MANAGERS, "Solo administradores pueden revocar sesiones"
    )
    if not current_user.store_id:
        raise AppException(
            message="Usuario sin tienda asociada",
            http_status=status.HTTP_400_BAD_REQUEST,
            error_code="USER_WITHOUT_STORE",
        )

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


async def revoke_user_sessions(
    user_public_id: str, current_user: User, db: AsyncSession
) -> RevokedSessionsResult:
    require_roles(
        current_user, STORE_MANAGERS, "Solo administradores pueden revocar sesiones"
    )
    if not current_user.store_id:
        raise AppException(
            message="Usuario sin tienda asociada",
            http_status=status.HTTP_400_BAD_REQUEST,
            error_code="USER_WITHOUT_STORE",
        )

    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)
        user_result = await db.execute(
            select(User).where(
                User.id == user_public_id, User.store_id == current_user.store_id
            )
        )
        target = user_result.scalar_one_or_none()
        if not target:
            raise UserNotFoundException(identifier=user_public_id)
        sessions_result = await db.execute(
            select(AuthSession).where(
                AuthSession.user_id == target.id, AuthSession.revoked_at.is_(None)
            )
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


async def revoke_all_sessions(
    current_user: User, db: AsyncSession
) -> RevokedSessionsResult:
    if not current_user.is_global_admin and str(current_user.role) != ROLE_SUPER_ADMIN:
        raise PermissionDeniedException(action="Operacion exclusiva para superadmin")

    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)
        result = await db.execute(
            select(AuthSession).where(AuthSession.revoked_at.is_(None))
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


async def request_password_reset(
    data: ForgotPasswordRequest, db: AsyncSession
) -> PasswordResetEmail | None:
    normalized_email = normalize_email(str(data.email))
    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)

        result = await db.execute(
            select(User).where(
                func.lower(User.email) == normalized_email, User.is_active.is_(True)
            )
        )
        user = result.scalar_one_or_none()

        if not user:
            return None

        token = generate_password_reset_token()
        user.password_reset_token_hash = hash_password_reset_token(token)
        user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
        )
        await db.commit()

        base_url = settings.FRONTEND_URL.rstrip("/")
        reset_path = settings.FRONTEND_RESET_PASSWORD_PATH
        return PasswordResetEmail(
            email_to=user.email,
            reset_url=f"{base_url}{reset_path}?token={token}",
        )
    finally:
        set_tenant_context(None, False)


async def reset_password(data: ResetPasswordRequest, db: AsyncSession) -> MessageResult:
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
            raise InvalidTokenException()

        user.hashed_password = hash_password(data.new_password)
        user.password_reset_token_hash = None
        user.password_reset_expires_at = None
        await db.commit()

        return {"message": "Contraseña actualizada correctamente"}
    finally:
        set_tenant_context(None, False)


async def change_password(
    data: ChangePasswordRequest, user: User, db: AsyncSession
) -> MessageResult:
    if not verify_password(data.current_password, user.hashed_password):
        raise AppException(
            message="La contraseña actual es incorrecta",
            http_status=status.HTTP_400_BAD_REQUEST,
            error_code="INCORRECT_PASSWORD",
        )

    user.hashed_password = hash_password(data.new_password)
    await db.commit()
    return {"message": "Contraseña actualizada correctamente"}
