from redis.asyncio import Redis, from_url
from core.config import settings

_redis: Redis | None = None

async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT_SECONDS,
            retry_on_timeout=True,
        )
    return _redis

async def close_redis():
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
