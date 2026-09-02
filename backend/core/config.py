import os
import re
import secrets
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


def _env_files() -> tuple[str, ...] | None:
    if os.getenv("ENV", "").lower() == Environment.PRODUCTION.value:
        return None
    candidate = Path(__file__).resolve().parents[2] / ".env"
    if candidate.is_file():
        return (str(candidate),)
    return None


class Settings(BaseSettings):
    PROJECT_NAME: str = "Shifty v2"
    VERSION: str = "0.1.0"
    ENV: Environment = Environment.DEVELOPMENT

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    # Claims estandar del JWT: permiten denylist por jti y evitan que un token
    # emitido para otro sistema que comparta el secreto sea aceptado aca.
    JWT_ISSUER: str = "shifty-api"
    JWT_AUDIENCE: str = "shifty"
    # Corto a proposito: el access token no es revocable hasta su exp, asi que
    # su vida define la ventana de un token robado.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30
    BCRYPT_ROUNDS: int = 12
    # Bloqueo por cuenta ante fuerza bruta de login (ASVS 2.2.1). El contador
    # vive en Redis, por email normalizado, independiente de la IP.
    LOGIN_LOCKOUT_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_WINDOW_SECONDS: int = 900
    ALLOW_PUBLIC_REGISTRATION: bool = True
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    FIELD_ENCRYPTION_KEY: str | None = None
    OTP_CODE_EXPIRE_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5
    # Tope acumulado por telefono (ventana 1h): pedir codigos nuevos ya no
    # resetea el presupuesto de intentos.
    OTP_MAX_FAILURES_PER_HOUR: int = 10
    OTP_MAX_REQUESTS_PER_HOUR: int = 5
    OTP_PROVIDER: str = "console"
    # Nunca exponer el codigo en la respuesta salvo opt-in explicito (tests).
    OTP_DEBUG_EXPOSE_CODE: bool = False
    PAYMENTS_CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    PAYMENTS_CIRCUIT_BREAKER_RECOVERY_SECONDS: int = 30
    MERCADOPAGO_OAUTH_CLIENT_ID: str | None = None
    MERCADOPAGO_OAUTH_CLIENT_SECRET: str | None = None
    MERCADOPAGO_OAUTH_REDIRECT_URI: str | None = None
    MERCADOPAGO_OAUTH_AUTH_URL: str = "https://auth.mercadopago.com/authorization"
    MERCADOPAGO_OAUTH_STATE_TTL_SECONDS: int = 900
    MERCADOPAGO_WEBHOOK_MAX_AGE_SECONDS: int = 300
    # Minutos que un turno queda reservado esperando el pago de la seña. Al
    # vencer, el slot vuelve a estar disponible para otro cliente.
    PAYMENT_HOLD_MINUTES: int = 30
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_SMS_FROM: str | None = None
    TWILIO_WHATSAPP_FROM: str | None = None
    EXPOSE_API_DOCS: bool = True
    MAX_REQUEST_BODY_BYTES: int = 32 * 1024
    # Solo JSON: la API no tiene endpoints con formularios, y aceptar
    # x-www-form-urlencoded habilitaba CSRF via <form> cross-site (los POST de
    # formulario son "simple requests" y no pasan por preflight de CORS).
    ALLOWED_WRITE_CONTENT_TYPES: str = "application/json"
    TRUST_PROXY_HEADERS: bool = True
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_FAIL_CLOSED: bool = False
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_GLOBAL_PER_MINUTE: int = 240
    RATE_LIMIT_AUTH_PER_MINUTE: int = 12
    RATE_LIMIT_PUBLIC_READ_PER_MINUTE: int = 120
    RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE: int = 20
    REDIS_MAX_CONNECTIONS: int = 100
    REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS: float = 2.0
    REDIS_SOCKET_TIMEOUT_SECONDS: float = 2.0
    REPORT_MAX_RANGE_DAYS: int = 370
    SENTRY_DSN: str | None = None
    OPS_ENABLE_PUBLIC_HEALTH: bool = True
    SLO_MAX_PENDING_WEBHOOKS: int = 200
    SLO_MAX_FAILED_WEBHOOKS: int = 20
    SLO_MAX_PENDING_OUTBOX: int = 200
    MERCADOPAGO_WEBHOOK_SECRET: str | None = None
    RUN_RUNTIME_CONTRACTS_ON_STARTUP: bool = False

    DATABASE_URL: str
    # Las migraciones necesitan DDL y CREATE EXTENSION, asi que corren con el
    # dueno de la base. La aplicacion se conecta con un rol restringido para
    # que las politicas de RLS efectivamente la alcancen.
    MIGRATION_DATABASE_URL: str | None = None
    # Dimensionamiento del pool de conexiones. Por defecto SQLAlchemy usa
    # 5 + 10 = 15 por proceso; con varios workers de Uvicorn mas Celery eso
    # agota el max_connections de Postgres. Se expone para ajustarlo al deploy.
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_RECYCLE_SECONDS: int = 1800
    REDIS_URL: str
    CELERY_BROKER_URL: str = "memory://"
    CELERY_RESULT_BACKEND_URL: str | None = None
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1
    CELERY_TASK_ACKS_LATE: bool = True
    CELERY_TASK_SOFT_TIME_LIMIT_SECONDS: int = 120
    CELERY_TASK_TIME_LIMIT_SECONDS: int = 150

    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USER: str
    SMTP_PASS: str
    EMAILS_FROM_EMAIL: str

    FRONTEND_URL: str = "http://localhost:3000"
    FRONTEND_RESET_PASSWORD_PATH: str = "/reset-password"
    PUBLIC_API_URL: str = "http://localhost:8000"

    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"

    @model_validator(mode="before")
    @classmethod
    def apply_production_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        env = str(data.get("ENV") or os.getenv("ENV", "")).lower()
        if env != Environment.PRODUCTION.value:
            return data

        production_data = dict(data)
        production_data.setdefault("ALLOW_PUBLIC_REGISTRATION", False)
        production_data.setdefault("COOKIE_SECURE", True)
        # Lax y no None: la cookie es credencial y SameSite=None la mandaba en
        # requests cross-site (CSRF). El frontend comparte site via nginx.
        production_data.setdefault("COOKIE_SAMESITE", "lax")
        production_data.setdefault("EXPOSE_API_DOCS", False)
        production_data.setdefault("RATE_LIMIT_FAIL_CLOSED", True)
        return production_data

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        # El secreto de firma se valida en TODO entorno que no sea desarrollo:
        # un staging con el placeholder del repo firma tokens forjables.
        if self.ENV != Environment.DEVELOPMENT:
            if (
                self.SECRET_KEY == "generate_a_very_secret_key_here_for_production"
                or len(self.SECRET_KEY) < 32
            ):
                raise ValueError(
                    "SECRET_KEY debe ser fuerte y unico fuera de desarrollo"
                )
        if self.ENV == Environment.PRODUCTION:
            if "localhost" in self.CORS_ORIGINS or "127.0.0.1" in self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS no debe incluir localhost en produccion")
            if "*" in self.CORS_ORIGINS:
                raise ValueError(
                    "CORS_ORIGINS no puede ser * con credenciales habilitadas"
                )
            if not self.RATE_LIMIT_FAIL_CLOSED:
                raise ValueError(
                    "RATE_LIMIT_FAIL_CLOSED debe ser true en produccion: sin Redis "
                    "no puede quedar todo sin limite"
                )
            if self.ACCESS_TOKEN_EXPIRE_MINUTES > 30:
                raise ValueError(
                    "ACCESS_TOKEN_EXPIRE_MINUTES no debe superar 30 en produccion"
                )
            if self.EXPOSE_API_DOCS:
                raise ValueError("EXPOSE_API_DOCS debe ser false en produccion")
            if not self.RATE_LIMIT_ENABLED:
                raise ValueError("RATE_LIMIT_ENABLED debe estar activo en produccion")
            if not self.COOKIE_SECURE:
                raise ValueError("COOKIE_SECURE debe ser true en produccion")
            if (
                self.FIELD_ENCRYPTION_KEY is not None
                and len(self.FIELD_ENCRYPTION_KEY) < 32
            ):
                raise ValueError(
                    "FIELD_ENCRYPTION_KEY debe tener al menos 32 caracteres en produccion"
                )
            if self.ALLOW_PUBLIC_REGISTRATION:
                raise ValueError(
                    "ALLOW_PUBLIC_REGISTRATION debe ser false en produccion"
                )
            if self.OTP_PROVIDER == "console":
                raise ValueError("OTP_PROVIDER no puede ser console en produccion")
            if self.OTP_DEBUG_EXPOSE_CODE:
                raise ValueError("OTP_DEBUG_EXPOSE_CODE debe ser false en produccion")
            if self.COOKIE_SAMESITE.lower() not in {"lax", "strict", "none"}:
                raise ValueError("COOKIE_SAMESITE debe ser lax, strict o none")
            if self.FRONTEND_URL.startswith(("http://localhost", "http://127.0.0.1")):
                raise ValueError(
                    "FRONTEND_URL no puede apuntar a localhost en produccion"
                )
            if self.PUBLIC_API_URL.startswith(("http://localhost", "http://127.0.0.1")):
                raise ValueError(
                    "PUBLIC_API_URL no puede apuntar a localhost en produccion"
                )
            if not self.FIELD_ENCRYPTION_KEY:
                raise ValueError("FIELD_ENCRYPTION_KEY es obligatorio en produccion")
        if self.PAYMENTS_CIRCUIT_BREAKER_FAILURE_THRESHOLD < 1:
            raise ValueError("PAYMENTS_CIRCUIT_BREAKER_FAILURE_THRESHOLD debe ser >= 1")
        if self.PAYMENTS_CIRCUIT_BREAKER_RECOVERY_SECONDS < 1:
            raise ValueError("PAYMENTS_CIRCUIT_BREAKER_RECOVERY_SECONDS debe ser >= 1")
        if self.MERCADOPAGO_OAUTH_STATE_TTL_SECONDS < 60:
            raise ValueError("MERCADOPAGO_OAUTH_STATE_TTL_SECONDS debe ser >= 60")
        if self.MERCADOPAGO_WEBHOOK_MAX_AGE_SECONDS < 60:
            raise ValueError("MERCADOPAGO_WEBHOOK_MAX_AGE_SECONDS debe ser >= 60")
        if self.PAYMENT_HOLD_MINUTES < 5:
            raise ValueError("PAYMENT_HOLD_MINUTES debe ser >= 5")
        if self.REDIS_MAX_CONNECTIONS < 1:
            raise ValueError("REDIS_MAX_CONNECTIONS debe ser >= 1")
        if self.CELERY_WORKER_PREFETCH_MULTIPLIER < 1:
            raise ValueError("CELERY_WORKER_PREFETCH_MULTIPLIER debe ser >= 1")
        if self.CELERY_TASK_SOFT_TIME_LIMIT_SECONDS < 1:
            raise ValueError("CELERY_TASK_SOFT_TIME_LIMIT_SECONDS debe ser >= 1")
        if (
            self.CELERY_TASK_TIME_LIMIT_SECONDS
            <= self.CELERY_TASK_SOFT_TIME_LIMIT_SECONDS
        ):
            raise ValueError(
                "CELERY_TASK_TIME_LIMIT_SECONDS debe ser mayor al soft time limit"
            )
        if self.MAX_REQUEST_BODY_BYTES < 1024:
            raise ValueError("MAX_REQUEST_BODY_BYTES no puede ser menor a 1024 bytes")
        if self.MAX_REQUEST_BODY_BYTES > 1024 * 1024:
            raise ValueError(
                "MAX_REQUEST_BODY_BYTES no debe superar 1MB sin revision de seguridad"
            )
        return self

    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


def _sanitize_settings_error(value: str) -> str:
    value = re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^\s]+", r"\1[redacted]", value)
    value = re.sub(
        r"(?i)(secret|token|password|pass|key)=([^\s,;]+)", r"\1=[redacted]", value
    )
    return value[:2000]


def _fallback_settings() -> Settings:
    cors_origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost,http://127.0.0.1,http://localhost:5173,http://127.0.0.1:5173",
    )
    return Settings.model_construct(
        PROJECT_NAME="Shifty v2",
        VERSION="0.1.0",
        ENV=Environment.DEVELOPMENT,
        # Aleatorio por proceso: aunque el BootErrorMiddleware responda 503 a
        # todo, ningun componente (Celery, scripts) debe poder firmar tokens
        # con un secreto conocido publicado en el repo.
        SECRET_KEY="boot-failed-" + secrets.token_urlsafe(32),
        ALGORITHM="HS256",
        JWT_ISSUER="shifty-api",
        JWT_AUDIENCE="shifty",
        ACCESS_TOKEN_EXPIRE_MINUTES=15,
        REFRESH_TOKEN_EXPIRE_DAYS=30,
        PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=30,
        BCRYPT_ROUNDS=12,
        LOGIN_LOCKOUT_MAX_ATTEMPTS=5,
        LOGIN_LOCKOUT_WINDOW_SECONDS=900,
        ALLOW_PUBLIC_REGISTRATION=False,
        COOKIE_SECURE=True,
        COOKIE_SAMESITE="lax",
        FIELD_ENCRYPTION_KEY="boot-failed-" + secrets.token_urlsafe(32),
        OTP_CODE_EXPIRE_MINUTES=10,
        OTP_MAX_ATTEMPTS=5,
        OTP_MAX_FAILURES_PER_HOUR=10,
        OTP_MAX_REQUESTS_PER_HOUR=5,
        OTP_PROVIDER="console",
        OTP_DEBUG_EXPOSE_CODE=False,
        PAYMENTS_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5,
        PAYMENTS_CIRCUIT_BREAKER_RECOVERY_SECONDS=30,
        MERCADOPAGO_OAUTH_CLIENT_ID=None,
        MERCADOPAGO_OAUTH_CLIENT_SECRET=None,
        MERCADOPAGO_OAUTH_REDIRECT_URI=None,
        MERCADOPAGO_OAUTH_AUTH_URL="https://auth.mercadopago.com/authorization",
        MERCADOPAGO_OAUTH_STATE_TTL_SECONDS=900,
        MERCADOPAGO_WEBHOOK_MAX_AGE_SECONDS=300,
        PAYMENT_HOLD_MINUTES=30,
        TWILIO_ACCOUNT_SID=None,
        TWILIO_AUTH_TOKEN=None,
        TWILIO_SMS_FROM=None,
        TWILIO_WHATSAPP_FROM=None,
        EXPOSE_API_DOCS=False,
        MAX_REQUEST_BODY_BYTES=32 * 1024,
        ALLOWED_WRITE_CONTENT_TYPES="application/json",
        TRUST_PROXY_HEADERS=True,
        RATE_LIMIT_ENABLED=False,
        RATE_LIMIT_FAIL_CLOSED=False,
        RATE_LIMIT_WINDOW_SECONDS=60,
        RATE_LIMIT_GLOBAL_PER_MINUTE=240,
        RATE_LIMIT_AUTH_PER_MINUTE=12,
        RATE_LIMIT_PUBLIC_READ_PER_MINUTE=120,
        RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE=20,
        REDIS_MAX_CONNECTIONS=100,
        REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS=2.0,
        REDIS_SOCKET_TIMEOUT_SECONDS=2.0,
        REPORT_MAX_RANGE_DAYS=370,
        SENTRY_DSN=None,
        OPS_ENABLE_PUBLIC_HEALTH=True,
        SLO_MAX_PENDING_WEBHOOKS=200,
        SLO_MAX_FAILED_WEBHOOKS=20,
        SLO_MAX_PENDING_OUTBOX=200,
        MERCADOPAGO_WEBHOOK_SECRET=None,
        RUN_RUNTIME_CONTRACTS_ON_STARTUP=False,
        DATABASE_URL="postgresql+asyncpg://invalid:invalid@localhost/invalid",
        MIGRATION_DATABASE_URL=None,
        DB_POOL_SIZE=10,
        DB_MAX_OVERFLOW=5,
        DB_POOL_RECYCLE_SECONDS=1800,
        REDIS_URL="redis://localhost:6379/0",
        CELERY_BROKER_URL="memory://",
        CELERY_RESULT_BACKEND_URL=None,
        CELERY_WORKER_PREFETCH_MULTIPLIER=1,
        CELERY_TASK_ACKS_LATE=True,
        CELERY_TASK_SOFT_TIME_LIMIT_SECONDS=120,
        CELERY_TASK_TIME_LIMIT_SECONDS=150,
        SMTP_HOST="placeholder",
        SMTP_PORT=587,
        SMTP_USER="placeholder",
        SMTP_PASS="placeholder",
        EMAILS_FROM_EMAIL="no-reply@example.com",
        FRONTEND_URL=os.getenv(
            "FRONTEND_URL",
            "http://localhost:3000",
        ),
        FRONTEND_RESET_PASSWORD_PATH="/reset-password",
        PUBLIC_API_URL=os.getenv("PUBLIC_API_URL", "http://localhost/api"),
        CORS_ORIGINS=cors_origins,
    )


SETTINGS_BOOT_ERROR: str | None = None


def _load_settings() -> Settings:
    # Pydantic Settings resolves required fields from environment at runtime,
    # but static typing cannot model that constructor contract precisely.
    return Settings()  # type: ignore[call-arg]


try:
    settings = _load_settings()
except Exception as exc:
    SETTINGS_BOOT_ERROR = _sanitize_settings_error(str(exc))
    settings = _fallback_settings()
