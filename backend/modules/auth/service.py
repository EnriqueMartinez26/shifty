from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import secrets
import smtplib
import ssl
from typing import NoReturn, TypedDict

import structlog
from fastapi import status
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from core.config import settings
from core.database import tenant_bypass
from core.exceptions import (
    AppException,
    AuthenticationException,
    InvalidTokenException,
    PermissionDeniedException,
    ResourceNotFoundException,
    RateLimitedException,
    UserNotFoundException,
)
from core.observability import report_mail_failure
from core.redis import REDIS_UNAVAILABLE_ERRORS, get_redis
from core.roles import (
    ROLE_CLIENT,
    STORE_MANAGERS,
    canonical_role,
    require_roles,
)
from core.security import (
    create_access_token,
    generate_password_reset_token,
    generate_refresh_token,
    hash_password,
    hash_password_async,
    hash_password_reset_token,
    hash_token,
    verify_password_async,
)
from modules.auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from modules.auth.session_model import AuthSession
from modules.users.model import User

__all__ = [
    "AuthTokenPair",
    "MessageResult",
    "PasswordResetEmail",
    "PasswordResetOutcome",
    "REFRESH_REUSE_GRACE_SECONDS",
    "REVOKED_BY_ADMIN",
    "REVOKED_BY_LOGOUT",
    "REVOKED_BY_OWNER",
    "REVOKED_BY_PASSWORD",
    "REVOKED_BY_ROTATION",
    "REVOKED_BY_REUSE",
    "REVOKED_BY_SUPERSEDED",
    "RevokedSessionsResult",
    "SessionClientContext",
    "access_token_for_user",
    "change_password",
    "hash_password_reset_token",
    "hash_token",
    "login_user",
    "list_user_sessions",
    "login_account_email",
    "logout_session",
    "normalize_email",
    "refresh_session",
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


def login_account_email(email: str) -> ColumnElement[bool]:
    """La cuenta que INICIA SESION con ``email`` (ya normalizado).

    PV-01 (2026-09-25): el email de un cliente es unico por tienda
    (``uq_users_client_email_per_store``) y el de las cuentas que inician
    sesion, unico global (``uq_users_email_non_client``). Un cliente puede
    compartir email con un profesional o con otros clientes de otras tiendas,
    asi que buscar solo por email podia devolver varias filas y
    ``scalar_one_or_none`` daba 500 (regla 16). Excluir a los clientes deja a
    lo sumo UNA fila: la que el indice unico parcial garantiza. Los clientes
    no inician sesion (portal por telefono + OTP).

    Es el filtro del login, del olvido de clave y del pre-chequeo de alta del
    personal y de los admins.
    """
    return and_(User.email == email, User.role != ROLE_CLIENT)


# Hash de sacrificio para igualar el tiempo de respuesta cuando el email no
# existe. Sin esto, la diferencia entre "no hay usuario" (respuesta rapida) y
# "password incorrecta" (bcrypt lento) permite enumerar cuentas por timing.
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(24))

logger = structlog.get_logger()

# D-20260928-01: segundos durante los que reusar un refresh revocado POR
# ROTACION se toma como carrera propia (dos pestanas, reintento tras una
# respuesta perdida) y no como robo.
REFRESH_REUSE_GRACE_SECONDS = 10
# Valor de ``auth_sessions.revoked_reason`` que escribe la rotacion.
REVOKED_BY_ROTATION = "rotated"
REVOKED_BY_LOGOUT = "logout"
REVOKED_BY_ADMIN = "admin"
REVOKED_BY_PASSWORD = "password"
REVOKED_BY_OWNER = "owner"
REVOKED_BY_REUSE = "reuse_detected"
REVOKED_BY_SUPERSEDED = "superseded"

# "Redis no esta" es el criterio unico de core.redis (AUD2-B7-14); ValueError
# suma el contador ilegible, que se trata igual que no poder leerlo.
_LOGIN_FAILURES_UNREADABLE: tuple[type[Exception], ...] = (
    *REDIS_UNAVAILABLE_ERRORS,
    ValueError,
)


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
    except _LOGIN_FAILURES_UNREADABLE:
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
    except REDIS_UNAVAILABLE_ERRORS:
        logger.warning("login_lockout_redis_unavailable")


async def _clear_login_failures(email_key: str) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    try:
        redis = await get_redis()
        await redis.delete(f"login:fail:{email_key}")
    except REDIS_UNAVAILABLE_ERRORS:
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
            # Sin context, starttls() no verifica certificado ni hostname
            # (PV-06): el link de reset y las credenciales SMTP viajaban a
            # quien se hiciera pasar por el servidor.
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
            smtp.send_message(message)
    except Exception as exc:
        # Nunca romper el flujo por el mail, pero tampoco fallar en silencio:
        # un SMTP caido deja a los usuarios sin recuperacion de cuenta.
        logger.warning(event, error_type=type(exc).__name__)
        report_mail_failure(component="auth", error_type=type(exc).__name__)


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
    revoked_reason: str = REVOKED_BY_ADMIN,
    preserve_refresh_token: str | None = None,
) -> int:
    """Revoca todas las sesiones vivas de un usuario.

    Es la pieza que faltaba en cambio/reset de contraseña, baja de usuario y
    revocacion de superadmin: sin esto, un refresh token robado sobrevivia 30
    dias a cualquier respuesta al incidente. ``preserve_refresh_token`` permite
    conservar la sesion desde la que el propio usuario hizo el cambio.
    NO commitea: corre dentro de la transaccion del flujo que la llama.
    """
    # The User row is the per-account mutex. Every code path that mutates
    # sessions takes this lock first, so a login or refresh cannot publish a
    # new session while this revocation is in flight.
    locked_user_ids = await _lock_user_rows(db, [user_id])
    if not locked_user_ids:
        return 0
    return await _revoke_sessions(
        db,
        user_ids=locked_user_ids,
        revoked_reason=revoked_reason,
        preserve_refresh_token=preserve_refresh_token,
    )


async def _lock_user_rows(db: AsyncSession, user_ids: list[str]) -> list[str]:
    """Lock existing User rows in a stable order, without flushing caller edits."""
    ids = sorted(set(user_ids))
    if not ids:
        return []
    # Several callers have already changed User attributes in this transaction.
    # Suppress autoflush so the explicit row lock is acquired before those
    # changes are written and before any AuthSession row is touched.
    with db.no_autoflush:
        result = await db.execute(
            select(User.id).where(User.id.in_(ids)).order_by(User.id).with_for_update()
        )
    return list(result.scalars().all())


async def _lock_users_matching(
    db: AsyncSession, *conditions: ColumnElement[bool]
) -> list[str]:
    """Lock a set of users in deterministic ID order for broad revocations."""
    with db.no_autoflush:
        result = await db.execute(
            select(User.id).where(*conditions).order_by(User.id).with_for_update()
        )
    return list(result.scalars().all())


async def _load_locked_user(db: AsyncSession, user_id: str) -> User | None:
    """Refresh a User ORM object after its row lock has been acquired."""
    if not await _lock_user_rows(db, [user_id]):
        return None
    result = await db.execute(
        select(User).where(User.id == user_id).execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def _supersede_rotated_history(db: AsyncSession, user_ids: list[str]) -> None:
    """Disarm prior rotated tokens while the caller holds their User locks.

    D-20261117-01: only events that revoke EVERY session of the user call this
    (reuse cascade, password change or reset, admin revocation). Logout and
    revoking one own session must not: an attacker holding a stolen session
    could otherwise switch off reuse detection for itself.
    """
    if not user_ids:
        return
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id.in_(user_ids),
            AuthSession.revoked_reason == REVOKED_BY_ROTATION,
        )
        .values(revoked_reason=REVOKED_BY_SUPERSEDED)
    )


async def _revoke_sessions(
    db: AsyncSession,
    *,
    user_ids: list[str],
    revoked_reason: str,
    preserve_refresh_token: str | None = None,
    conditions: tuple[ColumnElement[bool], ...] = (),
) -> int:
    """Supersede historial rotado y revoca las sesiones vivas del alcance.

    Las cuatro revocaciones hacian SELECT de todas las sesiones vivas, asignaban
    ``revoked_at`` en un ``for`` y contaban a mano; ``revoke_all_sessions`` (el
    boton de panico) hidrataba todas las de todas las tiendas y emitia un UPDATE
    por fila (B3-10, 2026-09-17). Ejecuta un UPDATE para desarmar el historial
    rotado y otro para revocar las sesiones vivas. NO commitea: corre en la
    transaccion del llamador.
    """
    # Rotated rows are security evidence, but cease to be replay triggers once
    # a later security event has invalidated their session family.
    await _supersede_rotated_history(db, user_ids)

    active_conditions = list(conditions)
    if preserve_refresh_token:
        active_conditions.append(
            AuthSession.refresh_token_hash != hash_token(preserve_refresh_token)
        )
    result = await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id.in_(user_ids),
            AuthSession.revoked_at.is_(None),
            *active_conditions,
        )
        .values(revoked_at=datetime.now(timezone.utc), revoked_reason=revoked_reason)
    )
    return int(getattr(result, "rowcount", 0) or 0)


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

    async with tenant_bypass(db):
        # Igualdad sobre la columna normalizada (ck_users_email_lower): bajo
        # RLS usa ix_users_email; lower(email) recorria users entera (F1-12).
        # Sin clientes: pueden compartir este email (PV-01).
        result = await db.execute(
            select(User).where(login_account_email(normalized_email))
        )
        user = result.scalar_one_or_none()

        # Se verifica SIEMPRE una password (real o de sacrificio) para que el
        # tiempo de respuesta no revele si el email existe. Se tolera un hash
        # NULL (fila corrupta/migrada) sin romper el timing ni delatar el caso.
        hashed = (user.hashed_password if user else None) or _DUMMY_PASSWORD_HASH
        password_ok = await verify_password_async(password, hashed)
        # Los clientes NO inician sesion en el panel: reservan por el flujo
        # publico. Negarles el login cierra la escalada intra-tenant (RLS aisla
        # entre tiendas, no entre roles) sin depender solo de las guardas por
        # endpoint. Mismo mensaje generico para no revelar el rol.
        if (
            not user
            or not user.is_active
            or not user.hashed_password
            or canonical_role(user) == ROLE_CLIENT
            or not password_ok
        ):
            await _register_login_failure(email_key)
            logger.warning("login_failed", email_fp=email_key, ip=context.ip_address)
            raise AuthenticationException(message="Credenciales incorrectas")

        # Serialize issuance with password/status revocations, then re-read the
        # credentials after waiting. A login checked against the old password
        # must not issue a session after a reset or access change committed.
        user = await _load_locked_user(db, user.id)
        password_still_valid = bool(
            user
            and user.hashed_password
            and (
                user.hashed_password == hashed
                or await verify_password_async(password, user.hashed_password)
            )
        )
        if (
            not user
            or not user.is_active
            or not user.hashed_password
            or canonical_role(user) == ROLE_CLIENT
            or not password_still_valid
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


async def _revocation_was_recent_rotation(
    db: AsyncSession, session_id: str
) -> tuple[bool, str | None]:
    """Indica si la revocacion fue una rotacion reciente y devuelve su motivo.

    Lee de la base y no del objeto cargado: el perdedor de la carrera lo cargo
    vivo y la rotacion ganadora recien se hizo visible despues de su UPDATE.
    """
    fila = (
        await db.execute(
            select(AuthSession.revoked_at, AuthSession.revoked_reason).where(
                AuthSession.id == session_id
            )
        )
    ).one_or_none()
    if fila is None:
        return False, None
    if fila.revoked_at is None:
        return False, fila.revoked_reason
    if fila.revoked_reason != REVOKED_BY_ROTATION:
        return False, fila.revoked_reason
    revoked_at: datetime = fila.revoked_at
    if revoked_at.tzinfo is None:
        # SQLite (tests) devuelve naive; Postgres aware.
        revoked_at = revoked_at.replace(tzinfo=timezone.utc)
    ventana = timedelta(seconds=REFRESH_REUSE_GRACE_SECONDS)
    return datetime.now(timezone.utc) - revoked_at < ventana, fila.revoked_reason


async def _handle_refresh_reuse(
    db: AsyncSession, session: AuthSession, ip: str | None
) -> NoReturn:
    """Reuso de un refresh ya revocado: 401, y segun el caso se revoca la familia.

    Lo detectan dos ramas de ``refresh_session`` -- el token llega ya
    revocado, y el UPDATE condicional de la rotacion que pierde la carrera -- y
    cada una tenia su copia LITERAL de este bloque (B3-09, 2026-09-17): una
    metrica o un cambio de politica agregado en una se olvidaba en la otra.
    Devuelve ``NoReturn`` para que mypy impida el ``return`` donde va un
    ``raise``.

    D-20261113-01 revisa D-20260928-01: solo reutilizar un refresh revocado por
    rotacion fuera de la ventana de gracia revoca las sesiones vivas restantes.
    Un token revocado por logout, admin o cambio de clave ya esta muerto; su
    repeticion no debe cerrar sesiones creadas despues de esa revocacion.
    D-20261117-01 revisa D-20261113-01: un logout o la revocacion de UNA sesion
    propia no desarman los ``rotated`` de las demas sesiones, asi que reusar uno
    de ellos despues sigue cascadeando.
    """
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise AuthenticationException(message="Sesion expirada")

    recent_rotation, revoked_reason = await _revocation_was_recent_rotation(
        db, session.id
    )
    if recent_rotation:
        logger.info("refresh_token_reuse_within_grace", user_id=session.user_id, ip=ip)
        raise AuthenticationException(message="Sesion expirada")

    # NULL/otro motivo incluye revocaciones historicas anteriores al registro
    # del motivo; sin evidencia de rotacion no se corta una sesion mas nueva.
    if revoked_reason != REVOKED_BY_ROTATION:
        if revoked_reason == REVOKED_BY_REUSE:
            # Este token ya disparo la cascada. Se conserva la deteccion, pero
            # repetirlo no debe revocar sesiones creadas desde entonces.
            logger.warning(
                "refresh_token_reuse_detected",
                user_id=session.user_id,
                revoked_sessions=0,
                cascade_claimed=False,
                ip=ip,
            )
            raise AuthenticationException(message="Sesion expirada")
        logger.info(
            "refresh_token_reuse_after_non_rotation_revocation",
            user_id=session.user_id,
            revoked_reason=revoked_reason,
            ip=ip,
        )
        raise AuthenticationException(message="Sesion expirada")

    # Marca primero al token que disparo el incidente. El lock de User que toma
    # refresh_session serializa la cascada con toda emision/revocacion de esa
    # cuenta; las demas filas rotadas pasan a `superseded` y ya no pueden
    # disparar otra cascada mas adelante.
    claim = await db.execute(
        update(AuthSession)
        .where(
            AuthSession.id == session.id,
            AuthSession.revoked_at.is_not(None),
            AuthSession.revoked_reason == REVOKED_BY_ROTATION,
        )
        .values(revoked_reason=REVOKED_BY_REUSE)
    )
    cascade_claimed = (getattr(claim, "rowcount", 0) or 0) == 1
    revoked = 0
    if cascade_claimed:
        revoked = await _revoke_sessions(
            db,
            user_ids=[session.user_id],
            revoked_reason=REVOKED_BY_REUSE,
        )
    await db.commit()
    logger.warning(
        "refresh_token_reuse_detected",
        user_id=session.user_id,
        revoked_sessions=revoked,
        cascade_claimed=cascade_claimed,
        ip=ip,
    )
    raise AuthenticationException(message="Sesion expirada")


async def refresh_session(
    refresh_token: str | None, db: AsyncSession, context: SessionClientContext
) -> AuthTokenPair:
    if not refresh_token:
        raise AuthenticationException(message="Sesion expirada")

    async with tenant_bypass(db):
        # The token hash is only used to discover the mutex owner. Re-read all
        # token state after waiting for that User row, since another refresh or
        # security revocation may have won while this request was queued.
        user_id_result = await db.execute(
            select(AuthSession.user_id).where(
                AuthSession.refresh_token_hash == hash_token(refresh_token)
            )
        )
        user_id = user_id_result.scalar_one_or_none()
        if user_id is None:
            raise AuthenticationException(message="Sesion expirada")

        user = await _load_locked_user(db, user_id)
        if not user:
            raise AuthenticationException(message="Sesion expirada")

        session_result = await db.execute(
            select(AuthSession)
            .where(AuthSession.refresh_token_hash == hash_token(refresh_token))
            .execution_options(populate_existing=True)
        )
        session = session_result.scalar_one_or_none()
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

        if session.revoked_at is not None:
            # La expirada ya se rechazo arriba: su repeticion nunca puede
            # iniciar un efecto lateral de replay/cascade.
            await _handle_refresh_reuse(db, session, context.ip_address)

        if not user.is_active:
            raise AuthenticationException(message="Sesion expirada")

        # Rotacion ATOMICA: revocar la sesion condicionado a que siga viva. Si
        # dos requests concurrentes traen el mismo refresh, solo uno logra el
        # UPDATE (rowcount==1); el otro ve rowcount==0 y se trata como reuso
        # (dentro de la ventana de gracia, 401 sin revocar nada). Sin esto,
        # ambos rotaban y quedaban dos sesiones vivas de un mismo refresh.
        now = datetime.now(timezone.utc)
        claim = await db.execute(
            update(AuthSession)
            .where(
                AuthSession.id == session.id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason=REVOKED_BY_ROTATION)
        )
        if (getattr(claim, "rowcount", 0) or 0) != 1:
            await _handle_refresh_reuse(db, session, context.ip_address)

        new_refresh_token = generate_refresh_token()
        new_session = _new_auth_session(user, new_refresh_token, context)
        db.add(new_session)
        await db.flush()
        access_token = access_token_for_user(user, new_session.id)
        await db.commit()

        return AuthTokenPair(access_token=access_token, refresh_token=new_refresh_token)


async def logout_session(refresh_token: str | None, db: AsyncSession) -> None:
    if not refresh_token:
        return

    async with tenant_bypass(db):
        user_id_result = await db.execute(
            select(AuthSession.user_id).where(
                AuthSession.refresh_token_hash == hash_token(refresh_token)
            )
        )
        user_id = user_id_result.scalar_one_or_none()
        if user_id is None or not await _lock_user_rows(db, [user_id]):
            return
        session_result = await db.execute(
            select(AuthSession)
            .where(AuthSession.refresh_token_hash == hash_token(refresh_token))
            .execution_options(populate_existing=True)
        )
        session = session_result.scalar_one_or_none()
        if session and session.revoked_at is None:
            session.revoked_at = datetime.now(timezone.utc)
            session.revoked_reason = REVOKED_BY_LOGOUT
            await db.commit()


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

    async with tenant_bypass(db):
        condiciones_usuario: list[ColumnElement[bool]] = [
            User.store_id == current_user.store_id
        ]
        if not current_user.is_global_admin:
            # La cuenta del superadmin no existe para un admin de tienda
            # (S-15): su sesion lleva el store_id de su tienda real, asi que
            # el boton de panico de la tienda la alcanzaba (AUD2-B3-02).
            condiciones_usuario.append(User.is_global_admin.is_(False))
        user_ids = await _lock_users_matching(db, *condiciones_usuario)
        affected = await _revoke_sessions(
            db,
            user_ids=user_ids,
            revoked_reason=REVOKED_BY_ADMIN,
            conditions=(AuthSession.store_id == current_user.store_id,),
        )
        await db.commit()
        return {"revoked_sessions": affected}


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

    async with tenant_bypass(db):
        condiciones_usuario: list[ColumnElement[bool]] = [
            User.id == user_public_id,
            User.store_id == current_user.store_id,
        ]
        if not current_user.is_global_admin:
            # La cuenta del superadmin no existe para un admin de tienda (S-15).
            condiciones_usuario.append(User.is_global_admin.is_(False))
        user_ids = await _lock_users_matching(db, *condiciones_usuario)
        if not user_ids:
            raise UserNotFoundException(identifier=user_public_id)
        affected = await _revoke_sessions(
            db, user_ids=user_ids, revoked_reason=REVOKED_BY_ADMIN
        )
        await db.commit()
        return {"revoked_sessions": affected}


async def revoke_all_sessions(
    current_user: User, db: AsyncSession
) -> RevokedSessionsResult:
    if not current_user.is_global_admin:
        raise PermissionDeniedException(action="Operacion exclusiva para superadmin")

    async with tenant_bypass(db):
        user_ids = await _lock_users_matching(db)
        affected = await _revoke_sessions(
            db, user_ids=user_ids, revoked_reason=REVOKED_BY_ADMIN
        )
        await db.commit()
        return {"revoked_sessions": affected}


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
    if not await _lock_user_rows(db, [user.id]):
        raise ResourceNotFoundException(resource="Sesión", identifier=session_id)
    result = await db.execute(
        select(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise ResourceNotFoundException(resource="Sesión", identifier=session_id)
    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        session.revoked_reason = REVOKED_BY_OWNER
        await db.commit()


async def request_password_reset(
    data: ForgotPasswordRequest, db: AsyncSession
) -> PasswordResetEmail | None:
    normalized_email = normalize_email(str(data.email))
    async with tenant_bypass(db):
        result = await db.execute(
            select(User).where(
                login_account_email(normalized_email), User.is_active.is_(True)
            )
        )
        user = result.scalar_one_or_none()

        # El token se genera y hashea SIEMPRE: la rama "no existe" hace el
        # mismo trabajo criptografico que la real para no filtrar por timing.
        token = generate_password_reset_token()
        token_hash = hash_password_reset_token(token)

        # Igual que el login: los clientes no acceden al panel, asi que tampoco
        # reciben reset (esto ademas corta el puente del cliente hacia un token).
        if not user or canonical_role(user) == ROLE_CLIENT:
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


async def reset_password(
    data: ResetPasswordRequest, db: AsyncSession
) -> PasswordResetOutcome:
    async with tenant_bypass(db):
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

        # Resets sharing a token serialize on User. Re-read after obtaining the
        # lock so a concurrently consumed or invalidated reset cannot win twice.
        user = await _load_locked_user(db, user.id)
        now = datetime.now(timezone.utc)
        reset_expires_at = user.password_reset_expires_at if user else None
        if reset_expires_at is not None and reset_expires_at.tzinfo is None:
            reset_expires_at = reset_expires_at.replace(tzinfo=timezone.utc)
        if (
            not user
            or not user.is_active
            or user.password_reset_token_hash != token_hash
            or reset_expires_at is None
            or reset_expires_at < now
        ):
            raise InvalidTokenException()

        user.hashed_password = await hash_password_async(data.new_password)
        user.password_reset_token_hash = None
        user.password_reset_expires_at = None
        # Un reset suele venir despues de un compromiso: si no se cierran las
        # sesiones vivas, el atacante conserva su refresh 30 dias mas.
        await revoke_sessions_for_user(db, user.id, revoked_reason=REVOKED_BY_PASSWORD)
        await db.commit()

        return PasswordResetOutcome(
            message="Contraseña actualizada correctamente",
            email_to=user.email,
        )


async def change_password(
    data: ChangePasswordRequest,
    user: User,
    db: AsyncSession,
    *,
    preserve_refresh_token: str | None = None,
) -> MessageResult:
    locked_user = await _load_locked_user(db, user.id)
    if not locked_user or not locked_user.is_active:
        raise AuthenticationException(message="Sesion expirada")
    if not await verify_password_async(
        data.current_password, locked_user.hashed_password
    ):
        raise AppException(
            message="La contraseña actual es incorrecta",
            http_status=status.HTTP_400_BAD_REQUEST,
            error_code="INCORRECT_PASSWORD",
        )
    if await verify_password_async(data.new_password, locked_user.hashed_password):
        raise AppException(
            message="La nueva contraseña no puede ser igual a la actual",
            http_status=status.HTTP_400_BAD_REQUEST,
            error_code="PASSWORD_UNCHANGED",
        )

    locked_user.hashed_password = await hash_password_async(data.new_password)
    # Un token de reset pendiente (quiza disparado por un atacante) no debe
    # sobrevivir al cambio de contraseña.
    locked_user.password_reset_token_hash = None
    locked_user.password_reset_expires_at = None
    # Cerrar las demas sesiones; la actual (cookie de refresh) se conserva.
    await revoke_sessions_for_user(
        db,
        locked_user.id,
        preserve_refresh_token=preserve_refresh_token,
        revoked_reason=REVOKED_BY_PASSWORD,
    )
    await db.commit()
    return {"message": "Contraseña actualizada correctamente"}
