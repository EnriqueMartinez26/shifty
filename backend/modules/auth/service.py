from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import secrets
import smtplib
from typing import TypedDict

import structlog
from fastapi import status
from redis.exceptions import RedisError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import _apply_tenant_context, set_tenant_context
from core.exceptions import (
    AppException,
    AuthenticationException,
    DuplicateAccountException,
    InvalidTokenException,
    PermissionDeniedException,
    RateLimitedException,
    RegistrationDisabledException,
    UserNotFoundException,
)
from core.redis import get_redis
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
    "PasswordResetOutcome",
    "RegistrationAdminResult",
    "RegistrationResult",
    "RevokedSessionsResult",
    "SessionClientContext",
    "access_token_for_user",
    "change_password",
    "hash_password_reset_token",
    "hash_token",
    "login_user",
    "list_user_sessions",
    "logout_session",
    "normalize_email",
    "refresh_session",
    "register_store_and_admin",
    "request_password_reset",
    "reset_password",
    "revoke_all_sessions",
    "revoke_own_session",
    "revoke_sessions_for_user",
    "revoke_store_sessions",
    "revoke_user_sessions",
    "send_password_changed_email",
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


@dataclass(frozen=True)
class PasswordResetOutcome:
    message: str
    # Para que el router notifique fuera de banda que la clave cambio.
    email_to: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


# Hash de sacrificio para igualar el tiempo de respuesta cuando el email no
# existe. Sin esto, la diferencia entre "no hay usuario" (respuesta rapida) y
# "password incorrecta" (bcrypt lento) permite enumerar cuentas por timing.
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(24))

logger = structlog.get_logger()


def _email_fingerprint(email: str) -> str:
    """Identificador estable del email para logs y claves de Redis, sin PII."""
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]


async def _login_failures(email_key: str) -> int:
    """Intentos fallidos acumulados para la cuenta (0 si Redis no responde y la
    politica es fail-open; excepcion 503 si es fail-closed)."""
    if not settings.RATE_LIMIT_ENABLED:
        return 0
    try:
        redis = await get_redis()
        value = await redis.get(f"login:fail:{email_key}")
        return int(value) if value else 0
    except RedisError, OSError, ValueError:
        if settings.RATE_LIMIT_FAIL_CLOSED:
            raise AppException(
                message="Servicio temporalmente no disponible",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_code="AUTH_BACKEND_UNAVAILABLE",
            )
        return 0


async def _register_login_failure(email_key: str) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    try:
        redis = await get_redis()
        key = f"login:fail:{email_key}"
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, settings.LOGIN_LOCKOUT_WINDOW_SECONDS)
        await pipe.execute()
    except RedisError, OSError:
        logger.warning("login_lockout_redis_unavailable")


async def _clear_login_failures(email_key: str) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    try:
        redis = await get_redis()
        await redis.delete(f"login:fail:{email_key}")
    except RedisError, OSError:
        logger.warning("login_lockout_redis_unavailable")


def access_token_for_user(user: User, session_id: str) -> str:
    """Emite el access token ATADO a una sesion del servidor.

    El claim ``sid`` es lo que vuelve revocable al access token: en cada request
    get_current_user valida que esa sesion siga viva, asi que revocar la sesion
    (logout, cambio de password, boton de panico) corta el token al instante en
    vez de esperar su exp. store_id/role/is_global_admin viajan solo como
    informacion para el cliente: la autorizacion y el contexto RLS se deciden
    releyendo al usuario de la base, nunca desde estos claims.
    """
    return create_access_token(
        data={
            "sub": user.public_id,
            "sid": session_id,
            "store_id": user.store_id,
            "role": canonical_role(user),
            "is_global_admin": user.is_global_admin,
        }
    )


def _send_email(message: EmailMessage, *, event: str) -> None:
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
            smtp.send_message(message)
    except Exception as exc:
        # Nunca romper el flujo por el mail, pero tampoco fallar en silencio:
        # un SMTP caido deja a los usuarios sin recuperacion de cuenta.
        logger.warning(event, error=str(exc), error_type=type(exc).__name__)


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
    _send_email(message, event="password_reset_email_failed")


def send_password_changed_email(email_to: str) -> None:
    """Aviso fuera de banda: si el cambio no lo hizo el dueño de la cuenta,
    este mail es su unica señal temprana de compromiso."""
    message = EmailMessage()
    message["Subject"] = "Tu contraseña fue modificada - Shifty"
    message["From"] = settings.EMAILS_FROM_EMAIL
    message["To"] = email_to
    message.set_content(
        "Te avisamos que la contraseña de tu cuenta de Shifty acaba de ser "
        "modificada y se cerraron las demas sesiones abiertas.\n\n"
        "Si no fuiste vos, restablecela de inmediato desde 'Olvide mi "
        "contraseña' y contactanos."
    )
    _send_email(message, event="password_changed_email_failed")


async def revoke_sessions_for_user(
    db: AsyncSession,
    user_id: str,
    *,
    preserve_refresh_token: str | None = None,
) -> int:
    """Revoca todas las sesiones vivas de un usuario.

    Es la pieza que faltaba en cambio/reset de contraseña, baja de usuario y
    revocacion de superadmin: sin esto, un refresh token robado sobrevivia 30
    dias a cualquier respuesta al incidente. ``preserve_refresh_token`` permite
    conservar la sesion desde la que el propio usuario hizo el cambio.
    NO commitea: corre dentro de la transaccion del flujo que la llama.
    """
    preserve_hash = (
        hash_token(preserve_refresh_token) if preserve_refresh_token else None
    )
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
    )
    now = datetime.now(timezone.utc)
    affected = 0
    for session in result.scalars().all():
        if preserve_hash and session.refresh_token_hash == preserve_hash:
            continue
        session.revoked_at = now
        affected += 1
    return affected


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
    email_key = _email_fingerprint(normalized_email)

    # Bloqueo por CUENTA (ademas del rate limit por IP, que se evade con IPs
    # distribuidas): tras N fallos en la ventana, la cuenta queda frenada.
    # Aplica igual a emails inexistentes para no funcionar como oraculo.
    if await _login_failures(email_key) >= settings.LOGIN_LOCKOUT_MAX_ATTEMPTS:
        logger.warning("login_locked_out", email_fp=email_key, ip=context.ip_address)
        raise RateLimitedException(
            retry_after=settings.LOGIN_LOCKOUT_WINDOW_SECONDS,
            headers={"Retry-After": str(settings.LOGIN_LOCKOUT_WINDOW_SECONDS)},
        )

    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(db)

        result = await db.execute(
            select(User).where(func.lower(User.email) == normalized_email)
        )
        user = result.scalar_one_or_none()

        # Se verifica SIEMPRE una password (real o de sacrificio) para que el
        # tiempo de respuesta no revele si el email existe. Se tolera un hash
        # NULL (fila corrupta/migrada) sin romper el timing ni delatar el caso.
        hashed = (user.hashed_password if user else None) or _DUMMY_PASSWORD_HASH
        password_ok = verify_password(password, hashed)
        if (
            not user
            or not user.is_active
            or not user.hashed_password
            or not password_ok
        ):
            await _register_login_failure(email_key)
            logger.warning("login_failed", email_fp=email_key, ip=context.ip_address)
            raise AuthenticationException(message="Credenciales incorrectas")

        # La sesion se crea ANTES de emitir el token: el access token queda
        # atado a su id (claim sid) y por lo tanto es revocable.
        session = _new_auth_session(
            user, refresh_token := generate_refresh_token(), context
        )
        db.add(session)
        await db.flush()
        access_token = access_token_for_user(user, session.id)
        await db.commit()
        await _clear_login_failures(email_key)
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
                AuthSession.refresh_token_hash == hash_token(refresh_token)
            )
        )
        session = result.scalar_one_or_none()

        if session and session.revoked_at is not None:
            # Reuso de un refresh ya rotado: la señal clasica de robo (el
            # atacante y la victima tienen el mismo token; el segundo en llegar
            # cae aca). Se revoca la familia entera y se deja rastro.
            revoked = await revoke_sessions_for_user(db, session.user_id)
            await db.commit()
            logger.warning(
                "refresh_token_reuse_detected",
                user_id=session.user_id,
                revoked_sessions=revoked,
                ip=context.ip_address,
            )
            raise AuthenticationException(message="Sesion expirada")

        expires_at = session.expires_at if session else None
        if expires_at is not None and expires_at.tzinfo is None:
            # SQLite (tests) devuelve naive; Postgres aware.
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if (
            not session
            or expires_at is None
            or expires_at <= datetime.now(timezone.utc)
        ):
            raise AuthenticationException(message="Sesion expirada")

        user_result = await db.execute(
            select(User).where(User.id == session.user_id, User.is_active.is_(True))
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise AuthenticationException(message="Sesion expirada")

        # Rotacion ATOMICA: revocar la sesion condicionado a que siga viva. Si
        # dos requests concurrentes traen el mismo refresh, solo uno logra el
        # UPDATE (rowcount==1); el otro ve rowcount==0 y se trata como reuso
        # (revoca la familia). Sin esto, ambos rotaban y quedaban dos sesiones
        # vivas de un mismo refresh.
        now = datetime.now(timezone.utc)
        claim = await db.execute(
            update(AuthSession)
            .where(
                AuthSession.id == session.id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        if (getattr(claim, "rowcount", 0) or 0) != 1:
            revoked = await revoke_sessions_for_user(db, session.user_id)
            await db.commit()
            logger.warning(
                "refresh_token_reuse_detected",
                user_id=session.user_id,
                revoked_sessions=revoked,
                ip=context.ip_address,
            )
            raise AuthenticationException(message="Sesion expirada")

        new_refresh_token = generate_refresh_token()
        new_session = _new_auth_session(user, new_refresh_token, context)
        db.add(new_session)
        await db.flush()
        access_token = access_token_for_user(user, new_session.id)
        await db.commit()

        return AuthTokenPair(access_token=access_token, refresh_token=new_refresh_token)
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


async def list_user_sessions(
    user: User, db: AsyncSession, current_refresh_token: str | None = None
) -> list[tuple[AuthSession, bool]]:
    """Sesiones vivas del propio usuario, marcando cual es la actual.

    Corre con el contexto de tenant real (lo fija get_current_user), asi que
    RLS ya acota a la tienda; el filtro por user_id acota a si mismo.
    """
    current_hash = hash_token(current_refresh_token) if current_refresh_token else None
    result = await db.execute(
        select(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(timezone.utc),
        )
        .order_by(AuthSession.created_at.desc())
    )
    return [
        (session, session.refresh_token_hash == current_hash)
        for session in result.scalars().all()
    ]


async def revoke_own_session(session_id: str, user: User, db: AsyncSession) -> None:
    """Cierra UNA sesion propia (ej.: 'ese telefono que perdi')."""
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == user.id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise UserNotFoundException(identifier=session_id)
    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        await db.commit()


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

        # El token se genera y hashea SIEMPRE: la rama "no existe" hace el
        # mismo trabajo criptografico que la real para no filtrar por timing.
        token = generate_password_reset_token()
        token_hash = hash_password_reset_token(token)

        if not user:
            return None

        user.password_reset_token_hash = token_hash
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


async def reset_password(
    data: ResetPasswordRequest, db: AsyncSession
) -> PasswordResetOutcome:
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
        # Un reset suele venir despues de un compromiso: si no se cierran las
        # sesiones vivas, el atacante conserva su refresh 30 dias mas.
        await revoke_sessions_for_user(db, user.id)
        await db.commit()

        return PasswordResetOutcome(
            message="Contraseña actualizada correctamente",
            email_to=user.email,
        )
    finally:
        set_tenant_context(None, False)


async def change_password(
    data: ChangePasswordRequest,
    user: User,
    db: AsyncSession,
    *,
    preserve_refresh_token: str | None = None,
) -> MessageResult:
    if not verify_password(data.current_password, user.hashed_password):
        raise AppException(
            message="La contraseña actual es incorrecta",
            http_status=status.HTTP_400_BAD_REQUEST,
            error_code="INCORRECT_PASSWORD",
        )
    if verify_password(data.new_password, user.hashed_password):
        raise AppException(
            message="La nueva contraseña no puede ser igual a la actual",
            http_status=status.HTTP_400_BAD_REQUEST,
            error_code="PASSWORD_UNCHANGED",
        )

    user.hashed_password = hash_password(data.new_password)
    # Un token de reset pendiente (quiza disparado por un atacante) no debe
    # sobrevivir al cambio de contraseña.
    user.password_reset_token_hash = None
    user.password_reset_expires_at = None
    # Cerrar las demas sesiones; la actual (cookie de refresh) se conserva.
    await revoke_sessions_for_user(
        db, user.id, preserve_refresh_token=preserve_refresh_token
    )
    await db.commit()
    return {"message": "Contraseña actualizada correctamente"}
