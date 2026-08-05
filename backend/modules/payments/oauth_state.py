from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from core.config import settings


class InvalidOAuthStateError(ValueError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _sign(payload: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_mercadopago_oauth_state(
    *, store_id: str, actor_id: str, ttl_seconds: int
) -> tuple[str, int, str, str]:
    expires_at = int(time.time()) + ttl_seconds
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = _b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
    payload = {
        "store_id": store_id,
        "actor_id": actor_id,
        "exp": expires_at,
        "nonce": secrets.token_urlsafe(12),
    }
    encoded_payload = _b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    state = f"{encoded_payload}.{_sign(encoded_payload)}"
    return state, expires_at, code_verifier, code_challenge


def mercadopago_oauth_state_cache_key(state: str) -> str:
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    return f"mercadopago:oauth-state:{digest}"


def parse_mercadopago_oauth_state(state: str) -> dict[str, Any]:
    try:
        encoded_payload, signature = state.split(".", 1)
    except ValueError as exc:
        raise InvalidOAuthStateError("state invalido") from exc

    expected_signature = _sign(encoded_payload)
    if not hmac.compare_digest(signature, expected_signature):
        raise InvalidOAuthStateError("state invalido")

    try:
        payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
    except Exception as exc:  # pragma: no cover - invalid external payload
        raise InvalidOAuthStateError("state invalido") from exc

    expires_at = int(payload.get("exp", 0) or 0)
    if expires_at < int(time.time()):
        raise InvalidOAuthStateError("state expirado")

    store_id = str(payload.get("store_id") or "").strip()
    actor_id = str(payload.get("actor_id") or "").strip()
    if not store_id or not actor_id:
        raise InvalidOAuthStateError("state invalido")

    return {
        "store_id": store_id,
        "actor_id": actor_id,
        "exp": expires_at,
        "nonce": str(payload.get("nonce") or ""),
    }
