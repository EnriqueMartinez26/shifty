from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import uuid
from typing import Any, cast

import bcrypt
from jose import jwt

from core.config import settings


def hash_password(password: str) -> str:
    # bcrypt solo mira los primeros 72 bytes; el truncado es explicito para no
    # depender del comportamiento de la libreria.
    password_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode("utf-8")[:72]
    return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))


def create_access_token(
    data: dict[str, Any], expires_delta: timedelta | None = None
) -> str:
    now = datetime.now(timezone.utc)
    to_encode = data.copy()
    expire = now + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    # Claims estandar: exp acota la vida, iat/jti permiten trazar y denylistear,
    # iss/aud evitan que un token de otro sistema con el mismo secreto (o de
    # otro proposito, como el state de OAuth) sea aceptado como credencial.
    to_encode.update(
        {
            "exp": expire,
            "iat": now,
            "jti": str(uuid.uuid4()),
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        }
    )
    return cast(
        str,
        jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM),
    )


def decode_token(token: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={
                "require_exp": True,
                "require_iat": True,
                "require_aud": True,
                "require_sub": True,
            },
        ),
    )


def generate_password_reset_token() -> str:
    return secrets.token_urlsafe(48)


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def hash_password_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    """SHA-256 pelado. Solo apto para tokens de alta entropia (reset de 384
    bits, refresh de 512): ahi el hash sin sal es seguro. NUNCA usarlo para
    secretos de espacio chico como un OTP de 6 digitos."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_otp_code(store_id: str, phone: str, code: str) -> str:
    """HMAC con pepper (SECRET_KEY) para el OTP.

    El espacio del codigo es de 10^6: con SHA-256 pelado, cualquiera con
    lectura de la tabla (backup, replica) lo invierte con una tabla
    precomputada de un millon de entradas. El HMAC ata el hash al secreto del
    servidor y al contexto (tienda + telefono), asi la tabla robada no alcanza.
    """
    material = f"{store_id}:{phone}:{code}".encode("utf-8")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), material, hashlib.sha256
    ).hexdigest()
