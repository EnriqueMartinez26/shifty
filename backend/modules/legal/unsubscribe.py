"""Link firmado de baja del mail promocional (Ley 25.326 art. 27; 2026-09-25).

El token es ``{store_id}.{client_id}.{vence}.{firma}``: ``vence`` en segundos
epoch y ``firma`` el HMAC-SHA256 (base64url) de lo anterior con una clave
derivada de ``SECRET_KEY`` solo para este uso (``core.security.derive_key``).
Vale ``UNSUBSCRIBE_TOKEN_TTL_DAYS``: un mail viejo no da de baja para siempre
a quien lo reenvio. Los ids no son secretos (el link va al buzon del propio
cliente); lo que no se puede es fabricar uno sin la clave. El token nunca se
loguea.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from core.config import settings
from core.security import derive_key

UNSUBSCRIBE_TOKEN_TTL_DAYS = 90
_PURPOSE = "marketing-unsubscribe"


def _sign(payload: str) -> str:
    digest = hmac.new(
        derive_key(_PURPOSE), payload.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def make_unsubscribe_token(
    store_id: str, client_id: str, *, now: datetime | None = None
) -> str:
    instante = now or datetime.now(timezone.utc)
    vence = int((instante + timedelta(days=UNSUBSCRIBE_TOKEN_TTL_DAYS)).timestamp())
    payload = f"{store_id}.{client_id}.{vence}"
    return f"{payload}.{_sign(payload)}"


def read_unsubscribe_token(
    token: str, *, now: datetime | None = None
) -> tuple[str, str] | None:
    """``(store_id, client_id)`` si la firma es valida y no vencio; si no, None."""
    partes = token.split(".")
    if len(partes) != 4 or not all(partes):
        return None
    store_id, client_id, vence, firma = partes
    if not hmac.compare_digest(firma, _sign(f"{store_id}.{client_id}.{vence}")):
        return None
    try:
        vence_en = int(vence)
    except ValueError:
        return None
    instante = now or datetime.now(timezone.utc)
    if instante.timestamp() > vence_en:
        return None
    return store_id, client_id


def unsubscribe_url(store_id: str, client_id: str) -> str:
    """Link de baja para el mail: la API publica (``PUBLIC_API_URL``)."""
    query = urlencode({"token": make_unsubscribe_token(store_id, client_id)})
    base = settings.PUBLIC_API_URL.rstrip("/")
    return f"{base}/public/unsubscribe" + "?" + query
