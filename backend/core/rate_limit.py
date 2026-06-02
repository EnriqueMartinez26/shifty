import hashlib
import json
import time

import structlog
from fastapi import HTTPException, Request, status
from redis.exceptions import RedisError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.config import Environment, settings
from core.redis import get_redis

logger = structlog.get_logger()


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _scope_headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _client_ip(headers: dict[str, str], fallback: str = "unknown") -> str:
    if settings.TRUST_PROXY_HEADERS:
        forwarded_for = headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip() or fallback
        real_ip = headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip() or fallback
    return fallback


def client_ip_from_request(request: Request) -> str:
    fallback = request.client.host if request.client else "unknown"
    return _client_ip({key.lower(): value for key, value in request.headers.items()}, fallback)


async def _hit_rate_limit(identifier: str, action: str, limit: int, window_seconds: int) -> int | None:
    now = int(time.time())
    bucket = now // window_seconds
    retry_after = window_seconds - (now % window_seconds)
    key = f"rate-limit:{action}:{_hash_identifier(identifier)}:{bucket}"

    redis = await get_redis()
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window_seconds + 5)
    if current > limit:
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
    identifier = f"{ip}:{subject.lower()}" if subject else ip
    try:
        retry_after = await _hit_rate_limit(identifier, action, limit, window)
    except RedisError as exc:
        logger.warning("rate_limit_redis_unavailable", action=action, error=str(exc))
        if settings.RATE_LIMIT_FAIL_CLOSED or settings.ENV == Environment.PRODUCTION:
            raise HTTPException(status_code=503, detail="Rate limit temporalmente no disponible") from exc
        return

    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas solicitudes. Intentá nuevamente más tarde.",
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


async def _send_rate_limit_response(send: Send, status_code: int, message: str, retry_after: int | None = None) -> None:
    body = json.dumps(
        {"success": False, "error_code": "RATE_LIMITED", "message": message},
        separators=(",", ":"),
    ).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    if retry_after is not None:
        headers.append((b"retry-after", str(retry_after).encode("ascii")))
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
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
            retry_after = await _hit_rate_limit(ip, action, limit, settings.RATE_LIMIT_WINDOW_SECONDS)
        except RedisError as exc:
            logger.warning("rate_limit_middleware_redis_unavailable", action=action, error=str(exc))
            if settings.RATE_LIMIT_FAIL_CLOSED or settings.ENV == Environment.PRODUCTION:
                await _send_rate_limit_response(send, 503, "Rate limit temporalmente no disponible")
                return
            await self.app(scope, receive, send)
            return

        if retry_after is not None:
            await _send_rate_limit_response(send, 429, "Demasiadas solicitudes. Intentá nuevamente más tarde.", retry_after)
            return

        await self.app(scope, receive, send)