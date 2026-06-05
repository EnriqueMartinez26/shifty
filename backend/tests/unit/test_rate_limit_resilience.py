import pytest
from fastapi import HTTPException
from redis.exceptions import RedisError
from starlette.requests import Request

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
async def test_rate_limit_fails_closed_when_redis_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", True)
    monkeypatch.setattr(settings, "ENV", Environment.DEVELOPMENT)

    async def broken_hit_rate_limit(*args, **kwargs):
        raise RedisError("redis down")

    monkeypatch.setattr(rate_limit, "_hit_rate_limit", broken_hit_rate_limit)

    with pytest.raises(HTTPException) as exc_info:
        await rate_limit.enforce_rate_limit(_request(), "public:test", 5)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Rate limit temporalmente no disponible"


@pytest.mark.asyncio
async def test_rate_limit_fails_open_in_development_when_redis_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", False)
    monkeypatch.setattr(settings, "ENV", Environment.DEVELOPMENT)

    async def broken_hit_rate_limit(*args, **kwargs):
        raise RedisError("redis down")

    monkeypatch.setattr(rate_limit, "_hit_rate_limit", broken_hit_rate_limit)

    await rate_limit.enforce_rate_limit(_request(), "public:test", 5)
