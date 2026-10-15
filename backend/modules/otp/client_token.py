"""Token del cliente: ata la autogestion a quien verifico el OTP.

Hallazgo del 2026-10-14: la autogestion ("Mis turnos" y la lista de espera
publica) se autorizaba solo con ``is_client_contact_verified``, "hay una
verificacion reciente de (tienda, telefono) contra el email de la ficha". Ese
predicado no estaba atado a QUIEN pregunta: durante los 30 minutos que vale
la verificacion, cualquiera que supiera el ``store_public_id`` (publico) y el
telefono listaba, cancelaba o reprogramaba los turnos de esa persona desde
otro dispositivo.

``/public/otp/verify`` devuelve ahora este token y la autogestion lo exige en
``X-Client-Token``, ADEMAS del chequeo en la base (defensa en profundidad:
tienen que pasar los dos).

Formato: JWT HS256 de PyJWT, la misma primitiva del access token del panel
(``core/security.py``), con otra clave y otros claims para que ninguno de los
dos sirva como el otro:

- clave propia, ``derive_key("client-self-service-token")``: un access token
  (firmado con ``SECRET_KEY``) no verifica aca, y este no verifica en
  ``decode_token``;
- ``aud`` y ``purpose`` propios: aunque las claves coincidieran, el
  ``audience`` cerrado de cada lado lo rechaza.

Claims: ``store`` (id interno de la tienda), ``phone`` (``normalize_phone``),
``vid`` (la ``OtpVerification`` concreta), ``emh`` (HMAC del email
verificado, no el email: el payload de un JWT se lee sin la clave), ``iat`` y
``exp`` (la verificacion mas la ventana de 30 minutos).

El token no se guarda en el servidor: lo que se revisa en la base es la
verificacion ``vid`` (vigente, de esa tienda y ese telefono, con ese email y
que el email siga siendo el de la ficha).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt

from core.config import settings
from core.security import derive_key

CLIENT_TOKEN_HEADER = "X-Client-Token"
# Igual a la ventana de ``is_client_contact_verified`` (30 minutos).
CLIENT_TOKEN_WINDOW_MINUTES = 30
CLIENT_TOKEN_AUDIENCE = "shifty-client-self-service"
CLIENT_TOKEN_PURPOSE = "client_self_service"
_ALGORITHM = "HS256"
# El tope de largo corta un header gigante antes de decodificarlo.
_MAX_TOKEN_LENGTH = 2048

# Motivos del rechazo: van SOLO al log del servidor (regla 20).
TOKEN_MISSING = "client_token_missing"
TOKEN_INVALID = "client_token_invalid"
TOKEN_STORE_MISMATCH = "client_token_other_store"
TOKEN_PHONE_MISMATCH = "client_token_other_phone"
TOKEN_VERIFICATION_NOT_FOUND = "client_token_verification_not_found"
TOKEN_EMAIL_MISMATCH = "client_token_email_mismatch"


@dataclass(frozen=True)
class ClientTokenClaims:
    store_id: str
    phone: str
    verification_id: str
    email_digest: str


def _signing_key() -> bytes:
    return derive_key("client-self-service-token")


def email_digest(email: str) -> str:
    """HMAC del email verificado (ya normalizado), con clave derivada."""
    return hmac.new(
        derive_key("client-self-service-email"),
        email.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def issue_client_token(
    *,
    store_id: str,
    phone: str,
    email: str,
    verification_id: str,
    verified_at: datetime,
) -> str:
    """Token de la verificacion ``verification_id``; vence con su ventana."""
    claims = {
        "iss": settings.JWT_ISSUER,
        "aud": CLIENT_TOKEN_AUDIENCE,
        "purpose": CLIENT_TOKEN_PURPOSE,
        "iat": verified_at,
        "exp": verified_at + timedelta(minutes=CLIENT_TOKEN_WINDOW_MINUTES),
        "jti": str(uuid.uuid4()),
        "store": store_id,
        "phone": phone,
        "vid": verification_id,
        "emh": email_digest(email),
    }
    return jwt.encode(claims, _signing_key(), algorithm=_ALGORITHM)


def read_client_token(
    token: str | None, *, store_id: str, phone: str
) -> tuple[ClientTokenClaims | None, str]:
    """Claims del token si vale para (tienda, telefono); si no, el motivo.

    ``phone`` ya pasado por ``normalize_phone``. Firma, vencimiento,
    ``iss``/``aud``/``purpose`` y que la tienda y el telefono sean los del
    pedido. La verificacion en la base la hace ``OtpService``.
    """
    if not token:
        return None, TOKEN_MISSING
    if len(token) > _MAX_TOKEN_LENGTH:
        return None, TOKEN_INVALID
    try:
        payload = jwt.decode(
            token,
            _signing_key(),
            algorithms=[_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=CLIENT_TOKEN_AUDIENCE,
            options={
                "require": [
                    "exp",
                    "iat",
                    "aud",
                    "iss",
                    "purpose",
                    "store",
                    "phone",
                    "vid",
                    "emh",
                ]
            },
            leeway=0,
        )
    except jwt.InvalidTokenError:
        return None, TOKEN_INVALID
    fields = (payload["store"], payload["phone"], payload["vid"], payload["emh"])
    if payload["purpose"] != CLIENT_TOKEN_PURPOSE or not all(
        isinstance(value, str) and value for value in fields
    ):
        return None, TOKEN_INVALID
    claims = ClientTokenClaims(*fields)
    if claims.store_id != store_id:
        return None, TOKEN_STORE_MISMATCH
    if claims.phone != phone:
        return None, TOKEN_PHONE_MISMATCH
    return claims, ""
