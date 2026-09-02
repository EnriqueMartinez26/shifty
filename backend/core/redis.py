import asyncio

from redis.asyncio import Redis, from_url

from core.config import settings

_redis: Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


def _build_client() -> Redis:
    return from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=settings.REDIS_SOCKET_TIMEOUT_SECONDS,
        retry_on_timeout=True,
    )


async def get_redis() -> Redis:
    """Cliente Redis compartido, atado al event loop vigente.

    El cliente async guarda conexiones ligadas al loop que las creo. En la app
    hay un solo loop y esto es un singleton normal; en tests (un loop por test)
    reusar el cliente del loop anterior deja la corrutina colgada para siempre.
    Si el loop cambio, se descarta el cliente y se crea uno nuevo.
    """
    global _redis, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis is None or _redis_loop is not loop:
        if _redis is not None:
            # El cliente viejo pertenece a un loop que ya no corre: cerrarlo
            # desde este loop puede fallar; alcanza con soltar la referencia.
            try:
                await _redis.aclose()
            except Exception:
                pass
        _redis = _build_client()
        _redis_loop = loop
    return _redis


async def close_redis() -> None:
    global _redis, _redis_loop
    if _redis:
        await _redis.aclose()
        _redis = None
        _redis_loop = None
