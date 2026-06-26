from collections.abc import Generator

import pytest
from core.config import settings
from main import app
from core.redis import get_redis

# Disable rate limit globally during tests
settings.RATE_LIMIT_ENABLED = False
# Allow public registration in tests (may be False in prod/fallback config)
settings.ALLOW_PUBLIC_REGISTRATION = True


class MockRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(
        self, key: str, value: object, nx: bool | None = None, px: int | None = None
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = str(value)
        return True

    async def setex(self, key: str, seconds: int, value: object) -> bool:
        self.store[key] = str(value)
        return True

    async def delete(self, key: str) -> int:
        if key in self.store:
            del self.store[key]
            return 1
        return 0

    async def incr(self, key: str) -> int:
        val = int(self.store.get(key, 0)) + 1
        self.store[key] = str(val)
        return val

    async def expire(self, key: str, seconds: int) -> bool:
        return True


@pytest.fixture(autouse=True)
def override_redis_dependency() -> Generator[None, None, None]:
    mock_redis = MockRedis()

    async def fake_get_redis() -> MockRedis:
        return mock_redis

    app.dependency_overrides[get_redis] = fake_get_redis
    yield
    if get_redis in app.dependency_overrides:
        del app.dependency_overrides[get_redis]
