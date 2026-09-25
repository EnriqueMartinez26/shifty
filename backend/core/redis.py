import asyncio

from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError

from core.config import settings

# Que cuenta como "Redis no esta". Vive aca, al lado del cliente, porque el
# criterio tiene que ser UNO: `core/idempotency.py` capturaba solo `RedisError`
# y `core/rate_limit.py` capturaba ademas `OSError`, asi que el mismo fallo
# -resolucion de nombres, socket cerrado antes de que redis-py lo envuelva- era
# fail-open en un lado y 500 en el otro, justo en las mutaciones que la
# idempotencia protege (AUD2-B7-14, 2026-09-20). `OSError` entra por ser el
# caso que redis-py no siempre alcanza a envolver; si alguna vez se demuestra
# que siempre lo envuelve, se saca de aca y los dos modulos cambian juntos.
REDIS_UNAVAILABLE_ERRORS: tuple[type[Exception], ...] = (RedisError, OSError)

_redis: Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None
_cache: Redis | None = None
_cache_loop: asyncio.AbstractEventLoop | None = None


def _build_client(url: str | None = None) -> Redis:
    return from_url(
        url or settings.REDIS_URL,
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


async def get_availability_cache() -> Redis:
    """Cliente del Redis de CACHE: solo para el cache de disponibilidad (F0-15).

    Ese Redis desaloja (`volatile-ttl`) y no persiste: lo que se pierde ahi se
    recalcula. Todo lo que es ESTADO (rate limit, idempotencia, lockout, OTP,
    OAuth, resultados de Celery) sigue en `get_redis`, un Redis `noeviction`:
    un desalojo no puede aflojar una proteccion. Sin `REDIS_CACHE_URL` (o con la
    misma URL) se devuelve el cliente de estado, sin abrir un segundo pool.
    Mismo ciclo de vida por loop que `get_redis`.
    """
    global _cache, _cache_loop
    url = settings.REDIS_CACHE_URL
    if not url or url == settings.REDIS_URL:
        return await get_redis()
    loop = asyncio.get_running_loop()
    if _cache is None or _cache_loop is not loop:
        if _cache is not None:
            try:
                await _cache.aclose()
            except Exception:
                pass
        _cache = _build_client(url)
        _cache_loop = loop
    return _cache


async def close_redis() -> None:
    """Cierra los dos clientes; un cierre fallido no deja al otro abierto."""
    global _redis, _redis_loop, _cache, _cache_loop
    cache, _cache, _cache_loop = _cache, None, None
    try:
        if cache:
            await cache.aclose()
    finally:
        if _redis:
            await _redis.aclose()
            _redis = None
            _redis_loop = None
