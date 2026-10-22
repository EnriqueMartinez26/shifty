"""``subject_quota_exhausted``: leer una cuota sin gastarla (paquete antiabuso, S3).

La cuota diaria por IP y tienda de la reserva publica se lee antes de
escribir y se consume despues de la reserva hecha, sobre la MISMA clave que
``subject_quota_allows``. Leer no consume; con Redis caido rige la politica de
la accion (``public-write``: 503 cerrada, ``None`` con aviso abierta).
"""

from __future__ import annotations

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

import core.rate_limit as rate_limit
from core.config import settings
from core.exceptions import AppException

ACCION = "public:booking:daily-per-ip-store"


class _Redis:
    def __init__(self, falla: bool = False) -> None:
        self.valores: dict[str, int] = {}
        self.falla = falla

    async def get(self, key: str) -> str | None:
        if self.falla:
            raise RedisConnectionError("caido")
        valor = self.valores.get(key)
        return None if valor is None else str(valor)

    def pipeline(self, transaction: bool = True) -> "_Pipe":
        return _Pipe(self)


class _Pipe:
    def __init__(self, redis: _Redis) -> None:
        self.redis = redis
        self.claves: list[str] = []

    def incr(self, key: str) -> None:
        self.claves.append(key)

    def expire(self, key: str, seconds: int) -> None:
        pass

    async def execute(self) -> list[object]:
        key = self.claves[0]
        self.redis.valores[key] = self.redis.valores.get(key, 0) + 1
        return [self.redis.valores[key], True]


def _usar(monkeypatch: pytest.MonkeyPatch, redis: _Redis) -> None:
    async def fake() -> _Redis:
        return redis

    monkeypatch.setattr(rate_limit, "get_redis", fake)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)


@pytest.mark.asyncio
async def test_leer_no_consume_y_ve_lo_que_consume_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _Redis()
    _usar(monkeypatch, redis)

    for _ in range(3):
        assert (
            await rate_limit.subject_quota_exhausted(
                ACCION, "s:1.2.3.4", limit=2, window_seconds=86400
            )
            is None
        )
    assert redis.valores == {}

    for _ in range(2):
        await rate_limit.subject_quota_allows(
            ACCION, "s:1.2.3.4", limit=2, window_seconds=86400
        )
    retry_after = await rate_limit.subject_quota_exhausted(
        ACCION, "s:1.2.3.4", limit=2, window_seconds=86400
    )

    assert retry_after is not None and 1 <= retry_after <= 86400
    assert list(redis.valores.values()) == [2]


@pytest.mark.asyncio
async def test_redis_caido_sigue_la_politica_de_la_accion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _usar(monkeypatch, _Redis(falla=True))

    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", False)
    assert (
        await rate_limit.subject_quota_exhausted(
            ACCION, "s:1.2.3.4", limit=2, window_seconds=86400
        )
        is None
    )

    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", True)
    with pytest.raises(AppException) as exc:
        await rate_limit.subject_quota_exhausted(
            ACCION, "s:1.2.3.4", limit=2, window_seconds=86400
        )
    assert exc.value.http_status == 503


@pytest.mark.asyncio
async def test_sin_rate_limit_no_lee_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    _usar(monkeypatch, _Redis(falla=True))
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)

    assert (
        await rate_limit.subject_quota_exhausted(
            ACCION, "s:1.2.3.4", limit=2, window_seconds=86400
        )
        is None
    )
