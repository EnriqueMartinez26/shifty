import json
import asyncio
from typing import Any
from redis.asyncio import Redis
from core.exceptions import IdempotencyInProgressException

PROCESSING_VALUE = "PROCESSING"
PROCESSING_TTL_MS = 30_000
RESULT_TTL_SECONDS = 86_400
MAX_WAIT_SECONDS = 10


async def idempotency_guard(key: str, redis: Redis) -> dict[str, Any] | None:
    """
    Guarda de idempotencia usando Redis.
    - Si el resultado ya existe, lo devuelve.
    - Si es una petición nueva, bloquea el proceso.
    """
    cache_key = f"idempotency:{key}"
    waited = 0.0

    while waited <= MAX_WAIT_SECONDS:
        cached = await redis.get(cache_key)
        if cached and cached != PROCESSING_VALUE:
            return json.loads(cached)

        if not cached:
            acquired = await redis.set(cache_key, PROCESSING_VALUE, nx=True, px=PROCESSING_TTL_MS)
            if acquired:
                return None

        await asyncio.sleep(0.25)
        waited += 0.25

    raise IdempotencyInProgressException()

async def idempotency_save(key: str, result: Any, redis: Redis):
    """Guarda el resultado exitoso para futuras peticiones idempotentes."""
    cache_key = f"idempotency:{key}"
    await redis.setex(cache_key, RESULT_TTL_SECONDS, json.dumps(result))


async def idempotency_release(key: str, redis: Redis) -> None:
    """Libera una llave que quedó en PROCESSING tras una excepción controlada."""
    cache_key = f"idempotency:{key}"
    if await redis.get(cache_key) == PROCESSING_VALUE:
        await redis.delete(cache_key)
