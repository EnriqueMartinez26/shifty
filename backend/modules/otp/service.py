from __future__ import annotations

import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from core.exceptions import OTPException, OTPRateLimitedException, ValidationException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import hash_token
from modules.otp.model import OtpVerification


def normalize_phone(raw_phone: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", raw_phone or "")
    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"
    if not cleaned.startswith("+"):
        cleaned = f"+{cleaned}"
    if len(cleaned) < 8 or len(cleaned) > 20:
        raise ValidationException("Telefono invalido")
    return cleaned


class OtpService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def request_code(
        self, *, store_id: str, phone: str, channel: str
    ) -> dict[str, object]:
        normalized_phone = normalize_phone(phone)
        if channel not in {"whatsapp", "sms"}:
            raise ValidationException("Canal invalido")

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
            code_hash=hash_token(code),
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
            raise OTPException()
        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            raise OTPRateLimitedException()

        otp.attempts += 1
        if not hmac.compare_digest(otp.code_hash, hash_token(code)):
            await self.db.commit()
            raise OTPException(
                message="Codigo OTP incorrecto.",
                error_code="OTP_INCORRECT",
                http_status=400,
            )

        otp.consumed_at = now
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
                OtpVerification.consumed_at.is_not(None),
                OtpVerification.consumed_at >= cutoff,
            )
            .order_by(OtpVerification.consumed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
