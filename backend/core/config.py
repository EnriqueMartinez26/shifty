from enum import Enum

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    PROJECT_NAME: str = "Shifty v2"
    VERSION: str = "0.1.0"
    ENV: Environment = Environment.DEVELOPMENT

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30
    ALLOW_PUBLIC_REGISTRATION: bool = True
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    FIELD_ENCRYPTION_KEY: str | None = None
    OTP_CODE_EXPIRE_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5
    OTP_PROVIDER: str = "console"
    OTP_DEBUG_EXPOSE_CODE: bool = True
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_SMS_FROM: str | None = None
    TWILIO_WHATSAPP_FROM: str | None = None
    EXPOSE_API_DOCS: bool = True
    MAX_REQUEST_BODY_BYTES: int = 32 * 1024
    ALLOWED_WRITE_CONTENT_TYPES: str = "application/json,application/x-www-form-urlencoded"
    TRUST_PROXY_HEADERS: bool = True
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_FAIL_CLOSED: bool = False
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_GLOBAL_PER_MINUTE: int = 240
    RATE_LIMIT_AUTH_PER_MINUTE: int = 12
    RATE_LIMIT_PUBLIC_READ_PER_MINUTE: int = 120
    RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE: int = 20
    REPORT_MAX_RANGE_DAYS: int = 370
    SENTRY_DSN: str | None = None
    OPS_ENABLE_PUBLIC_HEALTH: bool = True
    SLO_MAX_PENDING_WEBHOOKS: int = 200
    SLO_MAX_FAILED_WEBHOOKS: int = 20
    SLO_MAX_PENDING_OUTBOX: int = 200
    MERCADOPAGO_WEBHOOK_SECRET: str | None = None

    DATABASE_URL: str
    REDIS_URL: str
    CELERY_BROKER_URL: str

    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USER: str
    SMTP_PASS: str
    EMAILS_FROM_EMAIL: str

    FRONTEND_URL: str = "http://localhost:5173"
    FRONTEND_RESET_PASSWORD_PATH: str = "/reset-password"
    PUBLIC_API_URL: str = "http://localhost:8000"

    CORS_ORIGINS: str = (
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
    )

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.ENV == Environment.PRODUCTION:
            if self.SECRET_KEY == "generate_a_very_secret_key_here_for_production" or len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY debe ser fuerte y unico en produccion")
            if "localhost" in self.CORS_ORIGINS or "127.0.0.1" in self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS no debe incluir localhost en produccion")
            if self.EXPOSE_API_DOCS:
                raise ValueError("EXPOSE_API_DOCS debe ser false en produccion")
            if not self.RATE_LIMIT_ENABLED:
                raise ValueError("RATE_LIMIT_ENABLED debe estar activo en produccion")
            if not self.COOKIE_SECURE:
                raise ValueError("COOKIE_SECURE debe ser true en produccion")
            if not self.FIELD_ENCRYPTION_KEY or len(self.FIELD_ENCRYPTION_KEY) < 32:
                raise ValueError("FIELD_ENCRYPTION_KEY debe estar definido en produccion")
            if self.ALLOW_PUBLIC_REGISTRATION:
                raise ValueError("ALLOW_PUBLIC_REGISTRATION debe ser false en produccion")
        if self.COOKIE_SAMESITE.lower() not in {"lax", "strict", "none"}:
            raise ValueError("COOKIE_SAMESITE debe ser lax, strict o none")
        if self.MAX_REQUEST_BODY_BYTES < 1024:
            raise ValueError("MAX_REQUEST_BODY_BYTES no puede ser menor a 1024 bytes")
        if self.MAX_REQUEST_BODY_BYTES > 1024 * 1024:
            raise ValueError("MAX_REQUEST_BODY_BYTES no debe superar 1MB sin revision de seguridad")
        return self

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
