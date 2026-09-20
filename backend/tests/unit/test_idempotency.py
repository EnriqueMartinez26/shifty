import pytest
from redis.exceptions import RedisError, TimeoutError
from unittest.mock import AsyncMock

from core.idempotency import idempotency_guard, idempotency_release, idempotency_save


@pytest.mark.asyncio
async def test_idempotency_guard_fails_open_when_redis_times_out() -> None:
    redis = AsyncMock()
    redis.get.side_effect = TimeoutError("timeout")

    result = await idempotency_guard("booking-123", redis)

    assert result is None


@pytest.mark.asyncio
async def test_idempotency_release_and_save_swallow_redis_errors() -> None:
    redis = AsyncMock()
    redis.get.side_effect = TimeoutError("timeout")
    redis.setex.side_effect = TimeoutError("timeout")

    await idempotency_release("booking-123", redis)
    await idempotency_save("booking-123", {"ok": True}, redis)

    assert redis.get.await_count >= 1
    assert redis.setex.await_count == 1


@pytest.mark.asyncio
async def test_un_oserror_de_redis_tambien_es_fail_open() -> None:
    """AUD2-B7-14 (2026-09-20): la idempotencia leia "Redis caido" distinto.

    Sintoma: `core/idempotency.py` capturaba solo `RedisError`, mientras que
    `core/rate_limit.py` y cuatro modulos mas capturan `(RedisError, OSError)`.
    El mismo fallo -resolucion de nombres, socket cerrado antes de que redis-py
    lo envuelva- quedaba fail-open en el rate limit y 500 en la idempotencia,
    justo en las mutaciones que la idempotencia protege: el cliente reintenta
    un cobro contra un endpoint que en ese momento no tiene guarda. La regla 6
    documenta el fail-open, no el 500.
    """
    redis = AsyncMock()
    redis.get.side_effect = OSError("[Errno -2] Name or service not known")

    assert await idempotency_guard("booking-oserror", redis) is None


@pytest.mark.asyncio
async def test_save_y_release_tampoco_revientan_con_oserror() -> None:
    redis = AsyncMock()
    redis.get.side_effect = OSError("socket cerrado")
    redis.setex.side_effect = OSError("socket cerrado")

    await idempotency_release("booking-oserror", redis)
    await idempotency_save("booking-oserror", {"ok": True}, redis)

    assert redis.get.await_count >= 1
    assert redis.setex.await_count == 1


def test_el_criterio_de_redis_caido_se_define_una_sola_vez() -> None:
    """Las tres capas leen la MISMA tupla, no literales que se parecen.

    Que coincidan hoy por copia es lo que dejo de coincidir antes. El criterio
    vive en `core.redis` y los modulos que dependen del cliente lo importan.
    `core.availability_cache` entra en la lista porque AUD2-B7-03 le puso su
    propio `_REDIS_CAIDO = (RedisError, OSError)`: una cuarta copia del mismo
    criterio, escrita en paralelo a AUD2-B7-14.
    """
    import inspect

    import core.availability_cache as availability_cache
    import core.idempotency as idempotency
    import core.rate_limit as rate_limit
    from core.redis import REDIS_UNAVAILABLE_ERRORS

    assert REDIS_UNAVAILABLE_ERRORS == (RedisError, OSError)
    for modulo in (idempotency, rate_limit, availability_cache):
        fuente = inspect.getsource(modulo)
        assert "except REDIS_UNAVAILABLE_ERRORS" in fuente, modulo.__name__
        assert "except RedisError" not in fuente, modulo.__name__
        assert "except (RedisError" not in fuente, modulo.__name__
        assert "(RedisError, OSError)" not in fuente, modulo.__name__
