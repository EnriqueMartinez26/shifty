"""Un error de Redis se loguea por su tipo, nunca por su texto.

PV-22 (auditoria de privacidad, 2026-09-24): ``core/rate_limit.py``,
``core/idempotency.py`` y ``core/availability_cache.py`` volcaban
``str(exc)`` al log. El texto de un error de conexion de redis-py puede
repetir la URL de conexion, y esa URL lleva la clave de Redis. El OTP ya lo
hacia bien desde AUD2-B4-08 (solo ``error_type``); ahora los tres tambien.
``availability_cache`` ademas dejaba el traceback (``exc_info``), que repite
el mismo texto: el detalle completo sigue yendo a Sentry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from starlette.requests import Request
from structlog.testing import capture_logs

import core.availability_cache as availability_cache
import core.rate_limit as rate_limit
from core.config import settings
from core.idempotency import idempotency_guard, idempotency_release, idempotency_save
from tests.redis_pipeline_double import PipelineDouble

_SECRETO = "clave-de-redis-super-secreta"
_URL = f"redis://:{_SECRETO}@redis:6379/0"


def _error() -> RedisConnectionError:
    return RedisConnectionError(f"Error connecting to {_URL}. Connection refused.")


class _RedisCaido:
    async def get(self, *_args: object, **_kwargs: object) -> Any:
        raise _error()

    async def set(self, *_args: object, **_kwargs: object) -> Any:
        raise _error()

    async def setex(self, *_args: object, **_kwargs: object) -> Any:
        raise _error()

    async def getex(self, *_args: object, **_kwargs: object) -> Any:
        raise _error()

    async def incr(self, *_args: object, **_kwargs: object) -> Any:
        raise _error()

    async def expire(self, *_args: object, **_kwargs: object) -> Any:
        raise _error()

    def pipeline(self, transaction: bool = True) -> PipelineDouble:
        return PipelineDouble(self)


def _sin_secreto(eventos: Sequence[Mapping[str, Any]]) -> None:
    assert eventos, "no se registro el fallo"
    for evento in eventos:
        assert _SECRETO not in str(evento), evento
        assert "exc_info" not in evento, evento


@pytest.mark.asyncio
async def test_rate_limit_loguea_el_tipo_y_no_la_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", False)

    async def roto(*_args: object, **_kwargs: object) -> int:
        raise _error()

    monkeypatch.setattr(rate_limit, "_hit_rate_limit", roto)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/public/stores/x",
            "headers": [],
            "client": ("127.0.0.1", 1),
        }
    )

    async def app(_scope: Any, _receive: Any, _send: Any) -> None:
        return None

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: Any) -> None:
        return None

    with capture_logs() as eventos:
        await rate_limit.enforce_rate_limit(request, "public:test", 5)
        await rate_limit.RedisRateLimitMiddleware(app)(
            dict(request.scope), receive, send
        )

    fallos = [e for e in eventos if "redis_unavailable" in e["event"]]
    assert len(fallos) == 2
    assert all(e["error_type"] == "ConnectionError" for e in fallos)
    _sin_secreto(fallos)


@pytest.mark.asyncio
async def test_idempotencia_loguea_el_tipo_y_no_la_url() -> None:
    redis: Any = _RedisCaido()

    with capture_logs() as eventos:
        assert await idempotency_guard("k", redis) is None
        await idempotency_save("k", {"ok": True}, redis)
        await idempotency_release("k", redis)

    fallos = [e for e in eventos if e["event"] == "idempotency_redis_unavailable"]
    assert len(fallos) == 3
    _sin_secreto(fallos)


@pytest.mark.asyncio
async def test_invalidar_disponibilidad_loguea_el_tipo_y_no_la_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reportados: list[BaseException] = []
    monkeypatch.setattr(
        availability_cache,
        "report_exception",
        lambda exc, **_kw: reportados.append(exc),
    )
    with capture_logs() as eventos:
        await availability_cache.invalidate_availability(
            _RedisCaido(), "store-1", datetime(2026, 9, 24, tzinfo=timezone.utc)
        )

    fallos = [
        e for e in eventos if e["event"] == "availability_cache_invalidation_failed"
    ]
    assert len(fallos) == 1
    assert fallos[0]["error_type"] == "ConnectionError"
    _sin_secreto(fallos)
    assert reportados, "el detalle sigue yendo a Sentry"
