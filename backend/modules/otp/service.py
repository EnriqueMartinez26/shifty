from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.exceptions import OTPException, OTPRateLimitedException, ValidationException
from core.redis import REDIS_UNAVAILABLE_ERRORS, get_redis
from core.security import hash_otp_code
from modules.notifications.tasks import is_deliverable_email
from modules.otp.model import OtpVerification
from modules.users.model import User, UserRole

logger = structlog.get_logger()

# Un solo mensaje/codigo para TODO fallo de verificacion: distinguir
# "incorrecto" de "expirado/inexistente" le decia a un atacante si un telefono
# tiene un OTP vivo en esa tienda.
_OTP_INVALID = OTPException


def normalize_phone(raw_phone: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", raw_phone or "")
    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"
    if not cleaned.startswith("+"):
        cleaned = f"+{cleaned}"
    if len(cleaned) < 8 or len(cleaned) > 20:
        raise ValidationException("Telefono invalido")
    return cleaned


def canonical_phone_forms(normalized_phone: str) -> list[str]:
    """Las formas en que ese telefono puede estar guardado en ``users.phone``.

    AUD2-B4-03 (2026-09-19): ``normalize_phone`` canoniza el prefijo (``00``
    pasa a ``+``), pero el alta publica guarda los digitos TAL CUAL, con el
    ``00`` adelante (``public_api/schemas.py`` solo saca separadores y ``+``).
    La guarda del OTP comparaba contra dos formas y no encontraba al cliente
    que habia reservado con ``0054...``: el codigo salia al email tipeado y el
    secuestro de contacto volvia a abrirse. Hasta unificar el guardado (ver el
    reporte: exige migrar datos), la BUSQUEDA compara las tres formas.
    """
    digits = normalized_phone.lstrip("+")
    return [digits, f"+{digits}", f"00{digits}"]


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
    except REDIS_UNAVAILABLE_ERRORS as exc:
        # AUD2-B4-08: solo el tipo. El texto de un RedisError repite la
        # URL de conexion, que lleva credenciales.
        logger.warning("otp_budget_redis_unavailable", error_type=type(exc).__name__)
        if settings.RATE_LIMIT_FAIL_CLOSED:
            raise OTPRateLimitedException() from exc


def _otp_subject(store_name: str) -> str:
    """Mismo asunto para el codigo y para el aviso retenido: el asunto
    tampoco puede discriminar (AUD2-B4-05)."""
    return f"Tu codigo de verificacion - {store_name or 'Shifty'}"


def _code_body(code: str, store_name: str) -> str:
    tienda = store_name or "Shifty"
    return (
        "Hola,\n\n"
        f"Tu codigo para {tienda} es: {code}\n\n"
        f"Vence en {settings.OTP_CODE_EXPIRE_MINUTES} minutos. "
        "Si no pediste este codigo, ignora este mensaje.\n\n"
        "- El equipo de Shifty"
    )


def _withheld_body(store_name: str) -> str:
    """Aviso SIN codigo al email tipeado cuando el telefono ya tiene duenio.

    AUD2-B4-05 (2026-09-20): el camino retenido de B4-01 no mandaba nada, y
    quien pide controla la casilla que tipea. Pedir el codigo de un telefono
    ajeno con la casilla propia y mirar si llega ALGO decia si ese telefono es
    cliente de esa tienda; repetido contra varias tiendas, mapeaba donde es
    cliente una persona. Ahora llega un mail en los dos casos, con el mismo
    asunto y sin codigo.

    Queda un residuo declarado: quien LEE el cuerpo del mail que recibe sigue
    distinguiendo "codigo" de "aviso". Cerrarlo del todo exigiria no mandar
    nunca el codigo a una casilla tipeada, que es el caso del telefono que
    todavia no es de nadie. Lo que se cierra aca es el oraculo barato -el que
    solo mira si hubo entrega- y el vector automatizable.
    """
    tienda = store_name or "Shifty"
    return (
        "Hola,\n\n"
        f"Recibimos un pedido de codigo de verificacion para {tienda}.\n\n"
        "Si el telefono es tuyo, el codigo va a la direccion de correo que "
        "tenes registrada. Si no reconoces este pedido, ignora este mensaje: "
        "no hace falta que hagas nada.\n\n"
        "- El equipo de Shifty"
    )


# Entrega el mail (destino, asunto, cuerpo) FUERA del proceso de la API:
# ``notifications.tasks.enqueue_otp_email`` en el router (AUD2-B4-06). El
# servicio decide destino y contenido; quien llama decide el transporte, y
# nunca manda en linea.
DispatchScheduler = Callable[[str, str, str], None]


def _schedule_otp_mail(
    schedule_dispatch: DispatchScheduler,
    *,
    destination: str | None,
    withheld: bool,
    typed_email: str | None,
    code: str,
    store_name: str,
) -> None:
    """Un envio por pedido, coincida el email o no.

    AUD2-B4-05: el camino retenido tambien manda, sin codigo. Sin esto, "no
    me llego nada" era la respuesta a "¿este telefono es cliente de esta
    tienda?". Los dos caminos usan el mismo asunto y estan acotados por
    ``OTP_MAX_REQUESTS_PER_HOUR``.
    """
    asunto = _otp_subject(store_name)
    if destination:
        schedule_dispatch(destination, asunto, _code_body(code, store_name))
    elif withheld and typed_email:
        schedule_dispatch(typed_email, asunto, _withheld_body(store_name))


def _same_email(typed: str | None, registered: str) -> bool:
    if not typed:
        return False
    return typed.strip().lower() == registered.strip().lower()


class OtpService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _registered_client_email(
        self, store_id: str, normalized_phone: str
    ) -> str | None:
        """Email entregable del cliente de la tienda duenio de ese telefono.

        La reserva publica guarda el telefono del cliente solo con digitos y
        conserva el prefijo ``00``; ``normalize_phone`` lo canoniza a ``+``.
        Se buscan todas las formas equivalentes (AUD2-B4-03): si la guarda no
        encuentra al cliente, falla ABIERTA (manda al email tipeado).
        """
        result = await self.db.execute(
            select(User.email)
            .where(
                User.store_id == store_id,
                User.role == UserRole.CLIENT.value,
                User.phone.in_(canonical_phone_forms(normalized_phone)),
            )
            .order_by(User.created_at.desc())
            .limit(1)
        )
        registered = result.scalar_one_or_none()
        return registered if is_deliverable_email(registered) else None

    async def _resolve_destination(
        self, store_id: str, normalized_phone: str, email: str | None
    ) -> tuple[str | None, bool]:
        """(destino del codigo, retenido) para el canal email.

        B4-01 (2026-09-18): el codigo prueba posesion del EMAIL al que llega
        y la marca queda en el TELEFONO. Con el email del payload, cualquiera
        "verificaba" el telefono de otro. Si el telefono ya es de un cliente
        de la tienda con email entregable, el codigo solo va a ESE email y el
        tipeado tiene que coincidir; si no coincide, nadie recibe el codigo.
        Telefono nuevo o cliente sin email entregable: como siempre.
        """
        registered = await self._registered_client_email(store_id, normalized_phone)
        if registered is None:
            return email, False
        if _same_email(email, registered):
            return registered, False
        logger.info("otp_request_email_mismatch_for_known_client")
        return None, True

    async def _store_code(
        self, store_id: str, normalized_phone: str, channel: str, code: str
    ) -> OtpVerification:
        """Invalida los codigos vivos de ese telefono y guarda el nuevo."""
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
            expires_at=now + timedelta(minutes=settings.OTP_CODE_EXPIRE_MINUTES),
            provider_message_id="email" if channel == "email" else "console-dispatch",
        )
        self.db.add(otp)
        await self.db.commit()
        await self.db.refresh(otp)
        return otp

    async def request_code(
        self,
        *,
        store_id: str,
        phone: str,
        channel: str,
        email: str | None = None,
        store_name: str = "",
        schedule_dispatch: DispatchScheduler,
    ) -> dict[str, object]:
        """Genera y guarda el codigo; el mail lo entrega ``schedule_dispatch``
        fuera del proceso de la API (B4-01 lo saco del camino sincronico;
        AUD2-B4-06 lo saco tambien del request). La respuesta no espera al
        SMTP y su tiempo no depende del destino. El parametro es obligatorio
        a proposito, para que ningun llamador vuelva a mandar en linea."""
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

        destination: str | None = email
        withheld = False
        if channel == "email":
            destination, withheld = await self._resolve_destination(
                store_id, normalized_phone, email
            )

        # secrets, no random: un OTP con PRNG predecible se puede adivinar.
        code = f"{secrets.randbelow(1_000_000):06d}"
        otp = await self._store_code(store_id, normalized_phone, channel, code)

        if channel == "email":
            # Despues del commit (el codigo ya esta guardado cuando se encola
            # el mail) y fuera del proceso de la API: la respuesta es la
            # misma, y tarda lo mismo, haya envio o no, para no revelar si el
            # telefono es cliente ni convertir el SMTP en un oraculo.
            _schedule_otp_mail(
                schedule_dispatch,
                destination=destination,
                withheld=withheld,
                typed_email=email,
                code=code,
                store_name=store_name,
            )

        response = {"ok": True, "expires_at": otp.expires_at.isoformat()}
        if settings.OTP_DEBUG_EXPOSE_CODE:
            # Retenido: un codigo de mentira con la misma forma y siempre
            # distinto del guardado, que no lo conoce nadie (ni en debug).
            decoy = (int(code) + 1 + secrets.randbelow(999_999)) % 1_000_000
            response["debug_code"] = f"{decoy:06d}" if withheld else code
        return response

    async def verify_code(
        self, *, store_id: str, phone: str, code: str
    ) -> dict[str, object]:
        normalized_phone = normalize_phone(phone)

        await _consume_budget(
            "verify",
            store_id,
            normalized_phone,
            settings.OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR,
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
        # La UNICA marca valida de "este telefono demostro posesion".
        otp.verified_at = now
        await self.db.commit()
        return {"ok": True, "verified_at": now.isoformat(), "phone": normalized_phone}

    async def is_recently_verified(
        self, *, store_id: str, phone: str, window_minutes: int = 30
    ) -> bool:
        normalized_phone = normalize_phone(phone)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        result = await self.db.execute(
            select(OtpVerification.id)
            .where(
                OtpVerification.store_id == store_id,
                OtpVerification.phone == normalized_phone,
                OtpVerification.verified_at.is_not(None),
                OtpVerification.verified_at >= cutoff,
            )
            .order_by(OtpVerification.verified_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
