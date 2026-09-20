import hashlib
import ipaddress
import json
import time

import structlog
from fastapi import Request
from core.exceptions import AppException, RateLimitedException
from redis.exceptions import RedisError
from starlette.types import ASGIApp, Receive, Scope, Send

from core.config import settings
from core.redis import get_redis

logger = structlog.get_logger()

# Cuanto esperar cuando el limitador NO esta disponible (Redis caido y
# RATE_LIMIT_FAIL_CLOSED). No es la ventana del limite: la ventana describe
# cuando se libera una cuota, y aca no hay cuota que liberar sino un servicio
# que volver a intentar. Un valor chico y fijo le da al cliente un backoff
# concreto en vez de dejarlo reintentar a discrecion (AUD2-B7-09).
RETRY_AFTER_SIN_RATE_LIMIT_SECONDS = 5

# Un limite alcanzado y un limitador caido son eventos distintos y el front
# decide el reintento por el codigo, no por el status.
_ERROR_CODE_LIMITE_ALCANZADO = "RATE_LIMITED"
_ERROR_CODE_LIMITE_NO_DISPONIBLE = "RATE_LIMIT_UNAVAILABLE"
_MENSAJE_LIMITE_NO_DISPONIBLE = "Rate limit temporalmente no disponible"


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _scope_headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _client_ip(headers: dict[str, str], fallback: str = "unknown") -> str:
    """IP real del cliente detras del proxy.

    Se toma el ULTIMO elemento de X-Forwarded-For: es el unico que agrega
    nuestro nginx (que ademas reescribe el header). El primero lo controla el
    cliente — usarlo permitia elegir la "IP" rotandola por request y evadir
    todo el rate limiting. Cualquier valor que no parsee como IP se descarta.
    """
    if settings.TRUST_PROXY_HEADERS:
        forwarded_for = headers.get("x-forwarded-for")
        if forwarded_for:
            last_hop = forwarded_for.rsplit(",", 1)[-1].strip()
            ip = _valid_ip(last_hop)
            if ip:
                return ip
        real_ip = headers.get("x-real-ip")
        if real_ip:
            ip = _valid_ip(real_ip.strip())
            if ip:
                return ip
    return fallback


def client_ip_from_request(request: Request) -> str:
    fallback = request.client.host if request.client else "unknown"
    return _client_ip(
        {key.lower(): value for key, value in request.headers.items()}, fallback
    )


async def _hit_rate_limit(
    identifier: str, action: str, limit: int, window_seconds: int
) -> int | None:
    now = int(time.time())
    bucket = now // window_seconds
    retry_after = window_seconds - (now % window_seconds)
    key = f"rate-limit:{action}:{_hash_identifier(identifier)}:{bucket}"

    redis = await get_redis()
    # Pipeline: INCR y EXPIRE viajan juntos; sin esto, si el proceso muere en
    # el medio la clave queda sin TTL.
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds + 5)
    current, _ = await pipe.execute()
    if int(current) > limit:
        return max(1, retry_after)
    return None


async def enforce_rate_limit(
    request: Request,
    action: str,
    limit: int,
    window_seconds: int | None = None,
    subject: str | None = None,
) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return

    window = window_seconds or settings.RATE_LIMIT_WINDOW_SECONDS
    ip = client_ip_from_request(request)
    try:
        # Dos cubetas independientes: por IP y, si hay sujeto (email, telefono,
        # cuenta), por sujeto SOLO. Antes la clave era "ip:sujeto", que en la
        # practica era un limite por IP disfrazado: distribuyendo IPs habia
        # intentos ilimitados contra la misma cuenta.
        retry_after = await _hit_rate_limit(f"ip:{ip}", action, limit, window)
        if retry_after is None and subject:
            retry_after = await _hit_rate_limit(
                f"subject:{subject.lower()}", action, limit, window
            )
    except (RedisError, OSError) as exc:
        logger.warning("rate_limit_redis_unavailable", action=action, error=str(exc))
        if settings.RATE_LIMIT_FAIL_CLOSED:
            raise AppException(
                message=_MENSAJE_LIMITE_NO_DISPONIBLE,
                http_status=503,
                error_code=_ERROR_CODE_LIMITE_NO_DISPONIBLE,
                headers={"Retry-After": str(RETRY_AFTER_SIN_RATE_LIMIT_SECONDS)},
            ) from exc
        return

    if retry_after is not None:
        raise RateLimitedException(
            retry_after=retry_after,
            headers={"Retry-After": str(retry_after)},
        )


def _policy_for_request(method: str, path: str) -> tuple[str, int]:
    if path.startswith("/auth/"):
        return "auth", settings.RATE_LIMIT_AUTH_PER_MINUTE
    if path.startswith("/public/") and method in {"POST", "PUT", "PATCH", "DELETE"}:
        return "public-write", settings.RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE
    if path.startswith("/public/"):
        return "public-read", settings.RATE_LIMIT_PUBLIC_READ_PER_MINUTE
    return "global", settings.RATE_LIMIT_GLOBAL_PER_MINUTE


async def _send_rate_limit_response(
    send: Send,
    status_code: int,
    message: str,
    retry_after: int | None = None,
    error_code: str = _ERROR_CODE_LIMITE_ALCANZADO,
) -> None:
    """Sobre canonico del limitador, armado a mano por estar fuera del router.

    ``error_code`` es parametro y no una constante porque esta capa responde
    dos eventos distintos: un limite alcanzado (429) y un limitador que no esta
    disponible (503). Fijarlo en "RATE_LIMITED" hacia que el segundo se leyera
    como el primero (AUD2-B7-09).
    """
    body = json.dumps(
        {"success": False, "error_code": error_code, "message": message},
        separators=(",", ":"),
    ).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    if retry_after is not None:
        headers.append((b"retry-after", str(retry_after).encode("ascii")))
    await send(
        {"type": "http.response.start", "status": status_code, "headers": headers}
    )
    await send({"type": "http.response.body", "body": body})


class RedisRateLimitMiddleware:
    """Coarse per-IP rate limit applied before route handlers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not settings.RATE_LIMIT_ENABLED:
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        headers = _scope_headers(scope)
        client = scope.get("client") or ("unknown", 0)
        fallback_ip = str(client[0]) if client else "unknown"
        ip = _client_ip(headers, fallback_ip)
        action, limit = _policy_for_request(method, path)

        try:
            retry_after = await _hit_rate_limit(
                ip, action, limit, settings.RATE_LIMIT_WINDOW_SECONDS
            )
        except (RedisError, OSError) as exc:
            logger.warning(
                "rate_limit_middleware_redis_unavailable", action=action, error=str(exc)
            )
            if settings.RATE_LIMIT_FAIL_CLOSED:
                await _send_rate_limit_response(
                    send,
                    503,
                    _MENSAJE_LIMITE_NO_DISPONIBLE,
                    retry_after=RETRY_AFTER_SIN_RATE_LIMIT_SECONDS,
                    error_code=_ERROR_CODE_LIMITE_NO_DISPONIBLE,
                )
                return
            await self.app(scope, receive, send)
            return

        if retry_after is not None:
            await _send_rate_limit_response(
                send,
                429,
                "Demasiadas solicitudes. Intentá nuevamente más tarde.",
                retry_after,
            )
            return

        await self.app(scope, receive, send)
