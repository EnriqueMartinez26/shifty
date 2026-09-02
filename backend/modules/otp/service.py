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

from core.config import settings
from core.exceptions import OTPException, OTPRateLimitedException, ValidationException
from core.redis import get_redis
from core.security import hash_otp_code
from modules.otp.model import OtpVerification

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


class OtpService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def request_code(
        self, *, store_id: str, phone: str, channel: str
    ) -> dict[str, object]:
        normalized_phone = normalize_phone(phone)
        if channel not in {"whatsapp", "sms"}:
            raise ValidationException("Canal invalido")

        await _consume_budget(
            "req", store_id, normalized_phone, settings.OTP_MAX_REQUESTS_PER_HOUR
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
            provider_message_id="console-dispatch",
        )
        self.db.add(otp)
        await self.db.commit()
        await self.db.refresh(otp)

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
