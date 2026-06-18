import pytest
from redis.exceptions import TimeoutError
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
