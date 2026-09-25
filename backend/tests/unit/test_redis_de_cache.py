"""F0-15 (plan de rendimiento, decision 5): dos Redis, uno de cache y uno de estado.

Un solo Redis con politica de desalojo pone en juego el lockout de login, la
idempotencia de cobros, el presupuesto de OTP y el rate limit: bajo presion de
memoria, `allkeys-lru` los expulsa y la proteccion se afloja sin aviso. Con
`noeviction` en cambio el cache de disponibilidad llena la memoria y TODA
escritura falla. Se separan: el cache de disponibilidad va a `REDIS_CACHE_URL`
(`volatile-ttl`, sin persistencia, se puede perder) y el resto se queda en
`REDIS_URL` (`noeviction`, RDB).

`REDIS_CACHE_URL` es opcional: sin ella el cache comparte el cliente de estado,
como antes, sin abrir un segundo pool.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

import core.redis as core_redis
from core.config import settings


@pytest_asyncio.fixture
async def clientes_limpios() -> AsyncIterator[None]:
    await core_redis.close_redis()
    yield
    await core_redis.close_redis()


def _destino(cliente: object) -> tuple[str, int, int]:
    kwargs = cliente.connection_pool.connection_kwargs  # type: ignore[attr-defined]
    return str(kwargs["host"]), int(kwargs["port"]), int(kwargs["db"])


@pytest.mark.asyncio
async def test_el_cache_de_disponibilidad_usa_su_propio_redis(
    monkeypatch: pytest.MonkeyPatch, clientes_limpios: None
) -> None:
    monkeypatch.setattr(settings, "REDIS_URL", "redis://redis-estado:6379/0")
    monkeypatch.setattr(settings, "REDIS_CACHE_URL", "redis://redis-cache:6390/2")

    cache = await core_redis.get_availability_cache()
    estado = await core_redis.get_redis()

    assert _destino(cache) == ("redis-cache", 6390, 2)
    assert _destino(estado) == ("redis-estado", 6379, 0)
    # Mismos timeouts cortos que el de estado: un cache caido no puede
    # retener el request mas que un Redis de estado caido.
    kwargs = cache.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == settings.REDIS_SOCKET_TIMEOUT_SECONDS
    assert (
        kwargs["socket_connect_timeout"]
        == settings.REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS
    )
    # Singleton por loop, igual que el de estado.
    assert await core_redis.get_availability_cache() is cache


@pytest.mark.asyncio
async def test_sin_url_de_cache_se_comparte_el_cliente_de_estado(
    monkeypatch: pytest.MonkeyPatch, clientes_limpios: None
) -> None:
    monkeypatch.setattr(settings, "REDIS_URL", "redis://redis-estado:6379/0")
    monkeypatch.setattr(settings, "REDIS_CACHE_URL", None)

    assert await core_redis.get_availability_cache() is await core_redis.get_redis()


@pytest.mark.asyncio
async def test_el_apagado_cierra_los_dos_clientes(
    monkeypatch: pytest.MonkeyPatch, clientes_limpios: None
) -> None:
    monkeypatch.setattr(settings, "REDIS_URL", "redis://redis-estado:6379/0")
    monkeypatch.setattr(settings, "REDIS_CACHE_URL", "redis://redis-cache:6390/2")
    cache = await core_redis.get_availability_cache()
    await core_redis.get_redis()

    await core_redis.close_redis()

    assert await core_redis.get_availability_cache() is not cache
