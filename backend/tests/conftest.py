from collections.abc import Generator
import os

import pytest

_TEST_ENV = {
    "PROJECT_NAME": "Shifty test suite",
    "VERSION": "0.1.0-test",
    "ENV": "development",
    "SECRET_KEY": "test-only-not-a-secret",
    "ALGORITHM": "HS256",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
    "REFRESH_TOKEN_EXPIRE_DAYS": "30",
    "PASSWORD_RESET_TOKEN_EXPIRE_MINUTES": "30",
    "ALLOW_PUBLIC_REGISTRATION": "true",
    "COOKIE_SECURE": "false",
    "COOKIE_SAMESITE": "lax",
    "FIELD_ENCRYPTION_KEY": "",
    "OTP_CODE_EXPIRE_MINUTES": "10",
    "OTP_MAX_ATTEMPTS": "5",
    "OTP_PROVIDER": "console",
    "OTP_DEBUG_EXPOSE_CODE": "true",
    "PAYMENTS_CIRCUIT_BREAKER_FAILURE_THRESHOLD": "5",
    "PAYMENTS_CIRCUIT_BREAKER_RECOVERY_SECONDS": "30",
    "TWILIO_ACCOUNT_SID": "",
    "TWILIO_AUTH_TOKEN": "",
    "TWILIO_SMS_FROM": "",
    "TWILIO_WHATSAPP_FROM": "",
    "EXPOSE_API_DOCS": "true",
    "MAX_REQUEST_BODY_BYTES": "32768",
    "ALLOWED_WRITE_CONTENT_TYPES": "application/json,application/x-www-form-urlencoded",
    "TRUST_PROXY_HEADERS": "true",
    "RATE_LIMIT_ENABLED": "false",
    "RATE_LIMIT_FAIL_CLOSED": "false",
    "RATE_LIMIT_WINDOW_SECONDS": "60",
    "RATE_LIMIT_GLOBAL_PER_MINUTE": "240",
    "RATE_LIMIT_AUTH_PER_MINUTE": "12",
    "RATE_LIMIT_PUBLIC_READ_PER_MINUTE": "120",
    "RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE": "20",
    "REDIS_MAX_CONNECTIONS": "100",
    "REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS": "2.0",
    "REDIS_SOCKET_TIMEOUT_SECONDS": "2.0",
    "REPORT_MAX_RANGE_DAYS": "370",
    "SENTRY_DSN": "",
    "OPS_ENABLE_PUBLIC_HEALTH": "true",
    "SLO_MAX_PENDING_WEBHOOKS": "200",
    "SLO_MAX_FAILED_WEBHOOKS": "20",
    "SLO_MAX_PENDING_OUTBOX": "200",
    "MERCADOPAGO_WEBHOOK_SECRET": "",
    "RUN_RUNTIME_CONTRACTS_ON_STARTUP": "false",
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "REDIS_URL": "redis://localhost:6379/15",
    "CELERY_BROKER_URL": "memory://",
    "CELERY_RESULT_BACKEND_URL": "",
    "CELERY_WORKER_PREFETCH_MULTIPLIER": "1",
    "CELERY_TASK_ACKS_LATE": "true",
    "CELERY_TASK_SOFT_TIME_LIMIT_SECONDS": "120",
    "CELERY_TASK_TIME_LIMIT_SECONDS": "150",
    "SMTP_HOST": "localhost",
    "SMTP_PORT": "1025",
    "SMTP_USER": "test-user",
    "SMTP_PASS": "test-only-not-a-password",
    "EMAILS_FROM_EMAIL": "test@example.invalid",
    "FRONTEND_URL": "http://localhost:3000",
    "FRONTEND_RESET_PASSWORD_PATH": "/reset-password",
    "PUBLIC_API_URL": "http://localhost:8000",
    "CORS_ORIGINS": (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173"
    ),
}
os.environ.update(_TEST_ENV)

# Test configuration must exist before importing modules that instantiate Settings.
from core.config import settings  # noqa: E402
from main import app  # noqa: E402
from core.redis import get_redis  # noqa: E402

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
