import pytest
from core.config import settings
from main import app
from core.redis import get_redis

# Disable rate limit globally during tests
settings.RATE_LIMIT_ENABLED = False
# Allow public registration in tests (may be False in prod/fallback config)
settings.ALLOW_PUBLIC_REGISTRATION = True


class MockRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, nx=None, px=None):
        if nx and key in self.store:
            return None
        self.store[key] = str(value)
        return True

    async def setex(self, key, seconds, value):
        self.store[key] = str(value)
        return True

    async def delete(self, key):
        if key in self.store:
            del self.store[key]
            return 1
        return 0

    async def incr(self, key):
        val = int(self.store.get(key, 0)) + 1
        self.store[key] = str(val)
        return val

    async def expire(self, key, seconds):
        return True


@pytest.fixture(autouse=True)
def override_redis_dependency():
    mock_redis = MockRedis()

    async def fake_get_redis():
        return mock_redis

    app.dependency_overrides[get_redis] = fake_get_redis
    yield
    if get_redis in app.dependency_overrides:
        del app.dependency_overrides[get_redis]
