"""Validaciones de arranque en produccion.

Son la ultima linea entre una configuracion insegura y un deploy. Si dejan de
funcionar, el sistema arranca igual y nadie se entera hasta que hay un
incidente. Cada test apaga una sola proteccion y verifica que el arranque falle.
"""

from typing import Any

import pytest

from core.config import Environment, Settings

BASE: dict[str, Any] = {
    "ENV": "production",
    "SECRET_KEY": "una_clave_de_produccion_larga_y_unica_1234567890",
    "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/shifty",
    "REDIS_URL": "redis://redis:6379/0",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": 587,
    "SMTP_USER": "user",
    "SMTP_PASS": "pass",
    "EMAILS_FROM_EMAIL": "no-reply@example.com",
    "CORS_ORIGINS": "https://app.example.com",
    "FRONTEND_URL": "https://app.example.com",
    "PUBLIC_API_URL": "https://api.example.com",
    "FIELD_ENCRYPTION_KEY": "clave_de_cifrado_de_campos_de_32_o_mas",
    "RATE_LIMIT_ENABLED": True,
    "COOKIE_SECURE": True,
    "ALLOW_PUBLIC_REGISTRATION": False,
    "OTP_PROVIDER": "twilio",
    "OTP_DEBUG_EXPOSE_CODE": False,
    "EXPOSE_API_DOCS": False,
}


def _build(**overrides: Any) -> Settings:
    return Settings(**{**BASE, **overrides})


def test_una_configuracion_de_produccion_valida_arranca() -> None:
    settings = _build()
    assert settings.ENV == Environment.PRODUCTION


@pytest.mark.parametrize(
    ("override", "esperado"),
    [
        (
            {"SECRET_KEY": "generate_a_very_secret_key_here_for_production"},
            "SECRET_KEY",
        ),
        ({"SECRET_KEY": "corta"}, "SECRET_KEY"),
        ({"CORS_ORIGINS": "http://localhost:3000"}, "CORS_ORIGINS"),
        ({"CORS_ORIGINS": "http://127.0.0.1:3000"}, "CORS_ORIGINS"),
        ({"EXPOSE_API_DOCS": True}, "EXPOSE_API_DOCS"),
        ({"RATE_LIMIT_ENABLED": False}, "RATE_LIMIT_ENABLED"),
        ({"COOKIE_SECURE": False}, "COOKIE_SECURE"),
        ({"ALLOW_PUBLIC_REGISTRATION": True}, "ALLOW_PUBLIC_REGISTRATION"),
        ({"OTP_PROVIDER": "console"}, "OTP_PROVIDER"),
        ({"OTP_DEBUG_EXPOSE_CODE": True}, "OTP_DEBUG_EXPOSE_CODE"),
        ({"FIELD_ENCRYPTION_KEY": None}, "FIELD_ENCRYPTION_KEY"),
        ({"FIELD_ENCRYPTION_KEY": "corta"}, "FIELD_ENCRYPTION_KEY"),
        ({"FRONTEND_URL": "http://localhost:3000"}, "FRONTEND_URL"),
        ({"PUBLIC_API_URL": "http://127.0.0.1:8000"}, "PUBLIC_API_URL"),
        ({"COOKIE_SAMESITE": "invalido"}, "COOKIE_SAMESITE"),
    ],
)
def test_produccion_rechaza_configuraciones_inseguras(
    override: dict[str, Any], esperado: str
) -> None:
    with pytest.raises(ValueError, match=esperado):
        _build(**override)


@pytest.mark.parametrize(
    ("override", "esperado"),
    [
        ({"PAYMENTS_CIRCUIT_BREAKER_FAILURE_THRESHOLD": 0}, "FAILURE_THRESHOLD"),
        ({"PAYMENTS_CIRCUIT_BREAKER_RECOVERY_SECONDS": 0}, "RECOVERY_SECONDS"),
        ({"MERCADOPAGO_OAUTH_STATE_TTL_SECONDS": 30}, "STATE_TTL"),
        ({"MERCADOPAGO_WEBHOOK_MAX_AGE_SECONDS": 30}, "MAX_AGE"),
        ({"PAYMENT_HOLD_MINUTES": 1}, "PAYMENT_HOLD_MINUTES"),
        ({"REDIS_MAX_CONNECTIONS": 0}, "REDIS_MAX_CONNECTIONS"),
        ({"CELERY_WORKER_PREFETCH_MULTIPLIER": 0}, "PREFETCH"),
        ({"CELERY_TASK_SOFT_TIME_LIMIT_SECONDS": 0}, "SOFT_TIME_LIMIT"),
        ({"CELERY_TASK_TIME_LIMIT_SECONDS": 10}, "TIME_LIMIT"),
        ({"MAX_REQUEST_BODY_BYTES": 100}, "MAX_REQUEST_BODY_BYTES"),
        ({"MAX_REQUEST_BODY_BYTES": 5 * 1024 * 1024}, "MAX_REQUEST_BODY_BYTES"),
    ],
)
def test_los_limites_operativos_se_validan_en_cualquier_entorno(
    override: dict[str, Any], esperado: str
) -> None:
    """Estos no dependen de ENV: un valor absurdo rompe el arranque siempre."""
    with pytest.raises(ValueError, match=esperado):
        _build(ENV="development", **override)


def test_produccion_aplica_defaults_endurecidos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin declararlos, produccion no puede quedar con los valores de desarrollo."""
    endurecidos = (
        "ALLOW_PUBLIC_REGISTRATION",
        "COOKIE_SECURE",
        "EXPOSE_API_DOCS",
        "COOKIE_SAMESITE",
    )
    # El entorno de tests define estas variables; hay que sacarlas para observar
    # el default que aplica apply_production_defaults.
    for clave in endurecidos:
        monkeypatch.delenv(clave, raising=False)

    settings = Settings(
        **{k: v for k, v in BASE.items() if k not in endurecidos}
    )
    assert settings.ALLOW_PUBLIC_REGISTRATION is False
    assert settings.COOKIE_SECURE is True
    assert settings.EXPOSE_API_DOCS is False
    assert settings.COOKIE_SAMESITE == "none"
