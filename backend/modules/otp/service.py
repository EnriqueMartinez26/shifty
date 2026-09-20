from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

import structlog
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from core.config import settings
from core.exceptions import OTPException, OTPRateLimitedException, ValidationException
from core.redis import get_redis
from core.security import hash_otp_code
from modules.notifications.tasks import is_deliverable_email
from modules.otp.model import OtpVerification
from modules.users.model import User, UserRole

logger = structlog.get_logger()

# Un solo mensaje/codigo para TODO fallo de verificacion: distinguir
# "incorrecto" de "expirado/inexistente" le decia a un atacante si un telefono
# tiene un OTP vivo en esa tienda.
_OTP_INVALID = OTPException

# Motivo del rechazo, para el LOG DEL SERVIDOR. Nunca viaja al cliente: la
# respuesta sigue siendo un 403 con el mismo mensaje neutro (regla 20), porque
# cada motivo es un oraculo anonimo distinto ("ese telefono es cliente", "esa
# ficha tiene email cargado"). El log es lo unico que permite atender un ticket
# de un cliente legitimo trabado sin adivinar.
OTP_GATE_OK = "ok"
OTP_GATE_NEVER_VERIFIED = "never_verified"
OTP_GATE_EMAIL_MISMATCH = "verified_against_other_email"
OTP_GATE_NO_DELIVERABLE_CONTACT = "client_without_deliverable_email"


def mask_phone(phone: str | None) -> str:
    """Ultimos 4 digitos. Alcanza para cruzar con un ticket y no deja el
    numero completo en los logs; mismo criterio que `_mask_email` en
    `modules/notifications/tasks.py`."""
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return "***"
    return f"***{digits[-4:]}"


def normalize_phone(raw_phone: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", raw_phone or "")
    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"
    if not cleaned.startswith("+"):
        cleaned = f"+{cleaned}"
    if len(cleaned) < 8 or len(cleaned) > 20:
        raise ValidationException("Telefono invalido")
    return cleaned


def _normalize_email(email: str | None) -> str | None:
    cleaned = (email or "").strip().lower()
    return cleaned or None


def _budget_key(kind: str, store_id: str, phone: str) -> str:
    material = f"{store_id}:{phone}".encode("utf-8")
    return f"otp:{kind}:{hashlib.sha256(material).hexdigest()[:32]}"


async def _consume_budget(kind: str, store_id: str, phone: str, limit: int) -> None:
    """Presupuesto ACUMULADO por telefono en ventana de 1 hora.

    Independiente de la IP (que se puede rotar) y del registro OTP (que antes
    se renovaba con cada codigo nuevo, reseteando los intentos). Corta tanto la
    fuerza bruta del espacio de 10^6 como el SMS-bombing al titular del numero.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return
    try:
        redis = await get_redis()
        key = _budget_key(kind, store_id, phone)
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 3600)
        current, _ = await pipe.execute()
        if int(current) > limit:
            raise OTPRateLimitedException()
    except (RedisError, OSError) as exc:
        logger.warning("otp_budget_redis_unavailable", error=str(exc))
        if settings.RATE_LIMIT_FAIL_CLOSED:
            raise OTPRateLimitedException() from exc


async def _dispatch_code_by_email(email: str, code: str, store_name: str) -> None:
    from modules.notifications.tasks import _send_email

    tienda = store_name or "Shifty"
    asunto = f"Tu codigo de verificacion - {tienda}"
    cuerpo = (
        "Hola,\n\n"
        f"Tu codigo para {tienda} es: {code}\n\n"
        f"Vence en {settings.OTP_CODE_EXPIRE_MINUTES} minutos. "
        "Si no pediste este codigo, ignora este mensaje.\n\n"
        "- El equipo de Shifty"
    )
    try:
        enviado = await _send_email(email, asunto, cuerpo)
    except Exception as exc:  # nunca propaga: la respuesta debe ser neutra
        logger.warning("otp_email_dispatch_error", error_type=type(exc).__name__)
        return
    if not enviado:
        logger.warning("otp_email_dispatch_failed")


class OtpService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def request_code(
        self,
        *,
        store_id: str,
        phone: str,
        channel: str,
        email: str | None = None,
        store_name: str = "",
    ) -> dict[str, object]:
        normalized_phone = normalize_phone(phone)
        if channel not in {"email", "whatsapp", "sms"}:
            raise ValidationException("Canal invalido")
        # Hasta 2026-09-10 NINGUN canal despachaba el codigo (solo se exponia
        # en la respuesta en desarrollo). Email es el unico con envio real;
        # whatsapp/sms quedan como canales de desarrollo con el codigo visible.
        if channel != "email" and settings.OTP_PROVIDER != "console":
            raise ValidationException(
                "Ese canal no esta disponible; pedi el codigo por email"
            )
        if channel == "email" and not email:
            raise ValidationException("Falta el email para enviar el codigo")

        await _consume_budget(
            "req", store_id, normalized_phone, settings.OTP_MAX_REQUESTS_PER_HOUR
        )

        destination = await self._dispatch_destination_for(
            store_id, normalized_phone, requested_email=email
        )

        # secrets, no random: un OTP con PRNG predecible se puede adivinar.
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.OTP_CODE_EXPIRE_MINUTES
        )
        now = datetime.now(timezone.utc)

        await self.db.execute(
            update(OtpVerification)
            .where(
                OtpVerification.store_id == store_id,
                OtpVerification.phone == normalized_phone,
                OtpVerification.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )

        otp = OtpVerification(
            store_id=store_id,
            phone=normalized_phone,
            channel=channel,
            # HMAC con pepper y contexto: un SHA-256 pelado de 6 digitos se
            # invierte con una tabla de 10^6 entradas ante cualquier lectura
            # de la tabla (backup, replica).
            code_hash=hash_otp_code(store_id, normalized_phone, code),
            expires_at=expires_at,
            email=destination,
            provider_message_id="email" if channel == "email" else "console-dispatch",
        )
        self.db.add(otp)
        await self.db.commit()
        await self.db.refresh(otp)

        if channel == "email" and destination:
            # Fuera de la transaccion (ya commiteada) y best-effort: la
            # respuesta es la misma haya salido o no, para no revelar si el
            # telefono existe ni convertir el SMTP en un oraculo. Tampoco dice
            # a que buzon fue: eso delataria si el telefono es cliente.
            await _dispatch_code_by_email(destination, code, store_name)

        response = {"ok": True, "expires_at": otp.expires_at.isoformat()}
        if settings.OTP_DEBUG_EXPOSE_CODE:
            response["debug_code"] = code
        return response

    async def verify_code(
        self, *, store_id: str, phone: str, code: str
    ) -> dict[str, object]:
        normalized_phone = normalize_phone(phone)

        await _consume_budget(
            "fail", store_id, normalized_phone, settings.OTP_MAX_FAILURES_PER_HOUR
        )

        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(OtpVerification)
            .where(
                OtpVerification.store_id == store_id,
                OtpVerification.phone == normalized_phone,
            )
            .order_by(OtpVerification.created_at.desc())
            .limit(1)
            # Lock de fila: sin esto, dos verify concurrentes leen el mismo
            # attempts y ambos incrementan a N+1 (read-modify-write), dejando
            # exceder OTP_MAX_ATTEMPTS. No-op en SQLite (tests).
            .with_for_update()
        )
        otp = result.scalar_one_or_none()
        if not otp or otp.is_consumed or otp.is_expired:
            raise _OTP_INVALID()
        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            raise OTPRateLimitedException()

        otp.attempts += 1
        expected = hash_otp_code(store_id, normalized_phone, code)
        if not hmac.compare_digest(otp.code_hash, expected):
            await self.db.commit()
            raise _OTP_INVALID()

        otp.consumed_at = now
        # Marca que alguien demostro posesion del EMAIL `otp.email`, NO del
        # telefono: el codigo viaja a una direccion, y el telefono solo es la
        # clave con la que se pidio. Cualquier privilegio que dependa del
        # telefono tiene que mirar tambien contra que email se verifico
        # (`may_book_with_otp` / `is_client_contact_verified`). 2026-09-20.
        otp.verified_at = now
        await self.db.commit()
        return {"ok": True, "verified_at": now.isoformat(), "phone": normalized_phone}

    async def client_contact_verification_reason(
        self, *, store_id: str, phone: str, window_minutes: int = 30
    ) -> str:
        """Motivo (para el log) del veredicto de `is_client_contact_verified`."""
        normalized_phone = normalize_phone(phone)
        contact = await self._deliverable_client_email(store_id, normalized_phone)
        if not contact:
            return OTP_GATE_NO_DELIVERABLE_CONTACT
        if await self._matches_verified_email(
            store_id=store_id,
            normalized_phone=normalized_phone,
            email=contact,
            window_minutes=window_minutes,
        ):
            return OTP_GATE_OK
        # Distinguir "nunca verifico" de "verifico contra otro buzon" es lo
        # unico que separa un cliente que no termino el flujo de un intento de
        # secuestro. Solo va al log.
        if await self._matches_verified_email(
            store_id=store_id,
            normalized_phone=normalized_phone,
            email=None,
            window_minutes=window_minutes,
        ):
            return OTP_GATE_EMAIL_MISMATCH
        return OTP_GATE_NEVER_VERIFIED

    async def is_client_contact_verified(
        self, *, store_id: str, phone: str, window_minutes: int = 30
    ) -> bool:
        """El email verificado COINCIDE con el contacto guardado de esa ficha.

        Es el unico predicado que habilita autogestion, historial y contacto:
        listar, cancelar o reprogramar turnos ajenos, y decidir si se trae
        `get_client_history` o `UNKNOWN_HISTORY`.

        False si no hay cliente con ese telefono en la tienda, si su email no
        es entregable (el tecnico `{tel}@store{id}.noreply`) o si la
        verificacion no registro email. 2026-09-20.
        """
        reason = await self.client_contact_verification_reason(
            store_id=store_id, phone=phone, window_minutes=window_minutes
        )
        return reason == OTP_GATE_OK

    async def booking_otp_reason(
        self, *, store_id: str, phone: str, window_minutes: int = 30
    ) -> str:
        """Motivo (para el log) del veredicto de `may_book_with_otp`."""
        normalized_phone = normalize_phone(phone)
        contact = await self._deliverable_client_email(store_id, normalized_phone)
        if contact:
            # Hay una victima posible: se exige lo mismo que para autogestion.
            return await self.client_contact_verification_reason(
                store_id=store_id, phone=phone, window_minutes=window_minutes
            )
        # Sin ficha (o con el email tecnico `.noreply`) no hay nada que
        # filtrar: basta con haber probado ALGUN buzon. El codigo fue a ese
        # email porque `_dispatch_destination_for` no tenia a quien proteger.
        if await self._matches_verified_email(
            store_id=store_id,
            normalized_phone=normalized_phone,
            email=None,
            window_minutes=window_minutes,
        ):
            return OTP_GATE_OK
        return OTP_GATE_NEVER_VERIFIED

    async def may_book_with_otp(
        self, *, store_id: str, phone: str, window_minutes: int = 30
    ) -> bool:
        """Gate del feature flag `otp_booking` al RESERVAR.

        NO recibe email a proposito. Exigir que el email del formulario
        coincida con el verificado no aportaba seguridad -- quien ataca
        controla los dos campos igual -- y rompia el wizard publico, que tiene
        el email del cliente y el del codigo como campos independientes y
        opcionales. La seguridad la da el PUNTO DE DESPACHO: si el telefono
        tiene ficha con email entregable, `_dispatch_destination_for` manda el
        codigo a ESE buzon y el solicitante ya no lo elige. 2026-09-20.
        """
        reason = await self.booking_otp_reason(
            store_id=store_id, phone=phone, window_minutes=window_minutes
        )
        return reason == OTP_GATE_OK

    async def _dispatch_destination_for(
        self, store_id: str, normalized_phone: str, *, requested_email: str | None
    ) -> str | None:
        """El buzon al que va el codigo. NO lo elige quien lo pide.

        Si ese telefono ya es un cliente de la tienda con email ENTREGABLE, el
        codigo va a ESE email y el del request se ignora. Sin esto,
        `/public/otp/request` (publico) convertia "saber un telefono" en
        "recibir el codigo de esa persona". 2026-09-20.

        Si no hay ficha, o su email es el tecnico `{tel}@store{id}.noreply`, el
        codigo va al email del request: un telefono sin ficha no tiene nada que
        filtrar y el alta legitima tiene que poder verificarse.
        """
        protected = await self._deliverable_client_email(store_id, normalized_phone)
        if protected:
            return protected
        return _normalize_email(requested_email)

    async def _matches_verified_email(
        self,
        *,
        store_id: str,
        normalized_phone: str,
        email: str | None,
        window_minutes: int,
    ) -> bool:
        """Hay una verificacion reciente de ese telefono contra ESE email.

        Con `email=None` la pregunta es "contra ALGUN email", que sigue siendo
        fail closed: exige `otp_verifications.email IS NOT NULL`.

        Es PRIVADO a proposito. Como API publica era el footgun que este fix
        vino a eliminar: un predicado que acepta un email arbitrario del
        llamador deja que cada call site elija mal (y el gate de reserva eligio
        el email del formulario, que el atacante tambien controla). La
        ramificacion vive en `may_book_with_otp` /
        `is_client_contact_verified`, en un solo lugar testeado. 2026-09-20.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        # Las filas sin email (anteriores al 2026-09-20) NUNCA matchean: por
        # igualdad porque `NULL = 'x'` es NULL, y con `email=None` porque se
        # pide explicitamente `IS NOT NULL`. Fail closed por SQL, no por
        # acordarse.
        email_clause: ColumnElement[bool] = OtpVerification.email.is_not(None)
        if email is not None:
            normalized_email = _normalize_email(email)
            if not normalized_email:
                return False
            email_clause = OtpVerification.email == normalized_email
        result = await self.db.execute(
            select(OtpVerification.id)
            .where(
                OtpVerification.store_id == store_id,
                OtpVerification.phone == normalized_phone,
                OtpVerification.verified_at.is_not(None),
                OtpVerification.verified_at >= cutoff,
                email_clause,
            )
            .order_by(OtpVerification.verified_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _deliverable_client_email(
        self, store_id: str, normalized_phone: str
    ) -> str | None:
        """El email ENTREGABLE del cliente de esa tienda con ese telefono."""
        # `users.phone` guarda el telefono tal como lo tipearon menos
        # `\s-()+` (validador del schema publico) y `otp_verifications.phone`
        # normalizado con `+` (`normalize_phone`). Se buscan las tres formas de
        # almacenamiento que produce ese par de reglas, incluida la del prefijo
        # internacional `00` (que el validador conserva y `normalize_phone`
        # traduce a `+`): encontrar la ficha solo endurece el chequeo, nunca lo
        # afloja, asi que no encontrarla trababa a un cliente legitimo con 403.
        bare = normalized_phone.lstrip("+")
        variants = {normalized_phone, bare, f"00{bare}"}
        result = await self.db.execute(
            select(User)
            .where(
                User.store_id == store_id,
                User.role == UserRole.CLIENT,
                User.phone.in_(variants),
            )
            .order_by(User.created_at.desc())
            .limit(1)
        )
        client = result.scalars().first()
        if not client or not is_deliverable_email(client.email):
            return None
        return _normalize_email(client.email)
