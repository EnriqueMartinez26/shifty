import pytest
from collections.abc import MutableMapping
from pytest import MonkeyPatch
from core.exceptions import AppException, RateLimitedException
from redis.exceptions import RedisError
from starlette.requests import Request
from typing import Any

import core.rate_limit as rate_limit
from core.config import Environment, settings


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/public/availability",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


@pytest.mark.asyncio
async def test_rate_limit_fails_closed_when_redis_is_unavailable(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", True)
    monkeypatch.setattr(settings, "ENV", Environment.DEVELOPMENT)

    async def broken_hit_rate_limit(*args: Any, **kwargs: Any) -> int:
        raise RedisError("redis down")

    monkeypatch.setattr(rate_limit, "_hit_rate_limit", broken_hit_rate_limit)

    with pytest.raises(AppException) as exc_info:
        await rate_limit.enforce_rate_limit(_request(), "public:test", 5)

    assert exc_info.value.http_status == 503
    assert exc_info.value.message == "Rate limit temporalmente no disponible"


@pytest.mark.asyncio
async def test_rate_limit_fails_open_in_development_when_redis_is_unavailable(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", False)
    monkeypatch.setattr(settings, "ENV", Environment.DEVELOPMENT)

    async def broken_hit_rate_limit(*args: Any, **kwargs: Any) -> int:
        raise RedisError("redis down")

    monkeypatch.setattr(rate_limit, "_hit_rate_limit", broken_hit_rate_limit)

    await rate_limit.enforce_rate_limit(_request(), "public:test", 5)


def test_rate_limit_policy_uses_public_write_bucket_for_unsafe_public_methods(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE", 7)

    action, limit = rate_limit._policy_for_request("POST", "/public/appointments")

    assert action == "public-write"
    assert limit == 7


def test_rate_limit_policy_uses_auth_bucket_for_auth_routes(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 3)

    action, limit = rate_limit._policy_for_request("POST", "/auth/login")

    assert action == "auth"
    assert limit == 3


@pytest.mark.asyncio
async def test_enforce_rate_limit_raises_429_with_retry_after(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)

    async def limited(*args: Any, **kwargs: Any) -> int:
        return 42

    monkeypatch.setattr(rate_limit, "_hit_rate_limit", limited)

    with pytest.raises(RateLimitedException) as exc_info:
        await rate_limit.enforce_rate_limit(_request(), "public:test", 5)

    assert exc_info.value.http_status == 429
    assert exc_info.value.error_code == "RATE_LIMITED"
    assert exc_info.value.headers == {"Retry-After": "42"}


@pytest.mark.asyncio
async def test_middleware_returns_429_response_with_retry_after(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_WINDOW_SECONDS", 60)

    async def limited(*args: Any, **kwargs: Any) -> int:
        return 17

    async def app(_scope: Any, _receive: Any, _send: Any) -> None:
        raise AssertionError("inner app should not run when request is limited")

    sent_messages: list[MutableMapping[str, Any]] = []
    middleware = rate_limit.RedisRateLimitMiddleware(app)
    monkeypatch.setattr(rate_limit, "_hit_rate_limit", limited)

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent_messages.append(message)

    await middleware(
        {
            "type": "http",
            "method": "GET",
            "path": "/public/availability",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        },
        receive,
        send,
    )

    start = sent_messages[0]
    assert start["status"] == 429
    assert (b"retry-after", b"17") in start["headers"]
    assert b"RATE_LIMITED" in sent_messages[1]["body"]


@pytest.mark.asyncio
async def test_middleware_con_redis_caido_no_dice_que_es_un_limite_de_tasa(
    monkeypatch: MonkeyPatch,
) -> None:
    """AUD2-B7-09 (2026-09-20): el 503 por Redis caido salia como RATE_LIMITED.

    Sintoma: con RATE_LIMIT_FAIL_CLOSED (obligatorio en produccion) y Redis sin
    responder, el middleware devolvia 503 con error_code "RATE_LIMITED" y sin
    Retry-After. El front decide el reintento por el codigo, no por el status:
    trataba una caida de Redis como un limite de tasa y reintentaba sin backoff
    contra un backend que justamente no puede limitarlo. El mismo evento por la
    otra capa (enforce_rate_limit) ya salia como RATE_LIMIT_UNAVAILABLE.
    """
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", True)

    async def broken(*args: Any, **kwargs: Any) -> int:
        raise RedisError("redis down")

    async def app(_scope: Any, _receive: Any, _send: Any) -> None:
        raise AssertionError("la app interna no corre si el limite falla cerrado")

    sent_messages: list[MutableMapping[str, Any]] = []
    middleware = rate_limit.RedisRateLimitMiddleware(app)
    monkeypatch.setattr(rate_limit, "_hit_rate_limit", broken)

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent_messages.append(message)

    await middleware(
        {
            "type": "http",
            "method": "GET",
            "path": "/public/availability",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        },
        receive,
        send,
    )

    start = sent_messages[0]
    assert start["status"] == 503
    assert b"RATE_LIMIT_UNAVAILABLE" in sent_messages[1]["body"]
    assert b"RATE_LIMITED" not in sent_messages[1]["body"]
    assert (
        b"retry-after",
        str(rate_limit.RETRY_AFTER_SIN_RATE_LIMIT_SECONDS).encode("ascii"),
    ) in start["headers"]


@pytest.mark.asyncio
async def test_las_dos_capas_describen_igual_un_redis_caido(
    monkeypatch: MonkeyPatch,
) -> None:
    """El mismo evento no puede tener dos codigos segun por donde salga."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", True)

    async def broken(*args: Any, **kwargs: Any) -> int:
        raise RedisError("redis down")

    monkeypatch.setattr(rate_limit, "_hit_rate_limit", broken)

    with pytest.raises(AppException) as exc_info:
        await rate_limit.enforce_rate_limit(_request(), "public:test", 5)

    assert exc_info.value.error_code == "RATE_LIMIT_UNAVAILABLE"
    assert exc_info.value.headers == {
        "Retry-After": str(rate_limit.RETRY_AFTER_SIN_RATE_LIMIT_SECONDS)
    }


@pytest.mark.asyncio
async def test_el_429_sigue_diciendo_rate_limited(monkeypatch: MonkeyPatch) -> None:
    """La guarda de verdad sigue viva: un limite alcanzado no se confunde."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_WINDOW_SECONDS", 60)

    async def limited(*args: Any, **kwargs: Any) -> int:
        return 17

    async def app(_scope: Any, _receive: Any, _send: Any) -> None:
        raise AssertionError("la app interna no corre si el request esta limitado")

    sent_messages: list[MutableMapping[str, Any]] = []
    middleware = rate_limit.RedisRateLimitMiddleware(app)
    monkeypatch.setattr(rate_limit, "_hit_rate_limit", limited)

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent_messages.append(message)

    await middleware(
        {
            "type": "http",
            "method": "GET",
            "path": "/public/availability",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        },
        receive,
        send,
    )

    assert sent_messages[0]["status"] == 429
    assert b'"error_code":"RATE_LIMITED"' in sent_messages[1]["body"]
    assert (b"retry-after", b"17") in sent_messages[0]["headers"]
