import asyncio
import json
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

import structlog

from core.exceptions import IdempotencyInProgressException

PROCESSING_VALUE = "PROCESSING"
PROCESSING_TTL_MS = 30_000
RESULT_TTL_SECONDS = 86_400
MAX_WAIT_SECONDS = 10
logger = structlog.get_logger()


def _log_redis_fallback(operation: str, key: str, exc: Exception) -> None:
    logger.warning(
        "idempotency_redis_unavailable",
        operation=operation,
        key=key,
        error_type=type(exc).__name__,
        error=str(exc),
    )


async def idempotency_guard(key: str, redis: Redis) -> dict[str, Any] | None:
    """
    Guarda de idempotencia usando Redis.
    - Si el resultado ya existe, lo devuelve.
    - Si es una petición nueva, bloquea el proceso.
    """
    cache_key = f"idempotency:{key}"
    waited = 0.0

    while waited <= MAX_WAIT_SECONDS:
        try:
            cached = await redis.get(cache_key)
            if cached and cached != PROCESSING_VALUE:
                if isinstance(cached, bytes):
                    cached = cached.decode("utf-8")
                return cast(dict[str, Any], json.loads(cached))

            if not cached:
                acquired = await redis.set(
                    cache_key, PROCESSING_VALUE, nx=True, px=PROCESSING_TTL_MS
                )
                if acquired:
                    return None
        except RedisError as exc:
            _log_redis_fallback("guard", cache_key, exc)
            return None

        await asyncio.sleep(0.25)
        waited += 0.25

    raise IdempotencyInProgressException()


async def idempotency_save(key: str, result: Any, redis: Redis) -> None:
    """Guarda el resultado exitoso para futuras peticiones idempotentes."""
    cache_key = f"idempotency:{key}"
    try:
        await redis.setex(cache_key, RESULT_TTL_SECONDS, json.dumps(result))
    except RedisError as exc:
        _log_redis_fallback("save", cache_key, exc)


async def idempotency_release(key: str, redis: Redis) -> None:
    """Libera una llave que quedó en PROCESSING tras una excepción controlada."""
    cache_key = f"idempotency:{key}"
    try:
        cached = await redis.get(cache_key)
        if cached in (PROCESSING_VALUE, PROCESSING_VALUE.encode("utf-8")):
            await redis.delete(cache_key)
    except RedisError as exc:
        _log_redis_fallback("release", cache_key, exc)
