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
    "RATE_LIMIT_FAIL_CLOSED": True,
    "COOKIE_SECURE": True,
    "OTP_PROVIDER": "twilio",
    "OTP_DEBUG_EXPOSE_CODE": False,
    "EXPOSE_API_DOCS": False,
    # El entorno de tests lo pone en "true" para los tests de /ops; produccion
    # lo exige apagado (AUD2-B7-12), igual que EXPOSE_API_DOCS.
    "OPS_ENABLE_PUBLIC_HEALTH": False,
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
        ({"OTP_PROVIDER": "console"}, "OTP_PROVIDER"),
        ({"OTP_DEBUG_EXPOSE_CODE": True}, "OTP_DEBUG_EXPOSE_CODE"),
        ({"FIELD_ENCRYPTION_KEY": None}, "FIELD_ENCRYPTION_KEY"),
        ({"FIELD_ENCRYPTION_KEY": "corta"}, "FIELD_ENCRYPTION_KEY"),
        ({"FRONTEND_URL": "http://localhost:3000"}, "FRONTEND_URL"),
        ({"PUBLIC_API_URL": "http://127.0.0.1:8000"}, "PUBLIC_API_URL"),
        ({"COOKIE_SAMESITE": "invalido"}, "COOKIE_SAMESITE"),
        ({"CORS_ORIGINS": "*"}, "CORS_ORIGINS"),
        ({"RATE_LIMIT_FAIL_CLOSED": False}, "RATE_LIMIT_FAIL_CLOSED"),
        ({"ACCESS_TOKEN_EXPIRE_MINUTES": 120}, "ACCESS_TOKEN_EXPIRE_MINUTES"),
        # AUD2-B7-12 (2026-09-20): el detalle del readiness venia abierto.
        ({"OPS_ENABLE_PUBLIC_HEALTH": True}, "OPS_ENABLE_PUBLIC_HEALTH"),
        # 2026-09-24: la base de MP es configurable para el emulador de
        # tests/e2e; en produccion otra base recibiria los tokens de MP.
        (
            {"MERCADOPAGO_API_BASE_URL": "http://host.docker.internal:9999"},
            "MERCADOPAGO_API_BASE_URL",
        ),
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
        # AUD2-B7-06 (2026-09-20): tres numericos que quedaron sin piso.
        ({"RATE_LIMIT_WINDOW_SECONDS": 0}, "RATE_LIMIT_WINDOW_SECONDS"),
        ({"MAX_UPLOAD_BODY_BYTES": 100}, "MAX_UPLOAD_BODY_BYTES"),
        (
            {"REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS": 0},
            "REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",
        ),
        ({"REDIS_SOCKET_TIMEOUT_SECONDS": 0}, "REDIS_SOCKET_TIMEOUT_SECONDS"),
    ],
)
def test_los_limites_operativos_se_validan_en_cualquier_entorno(
    override: dict[str, Any], esperado: str
) -> None:
    """Estos no dependen de ENV: un valor absurdo rompe el arranque siempre."""
    with pytest.raises(ValueError, match=esperado):
        _build(ENV="development", **override)


@pytest.mark.asyncio
async def test_una_ventana_de_rate_limit_en_cero_revienta_cada_request() -> None:
    """Por que RATE_LIMIT_WINDOW_SECONDS necesita piso (AUD2-B7-06, 2026-09-20).

    `_hit_rate_limit` hace `now // window_seconds`. Con la ventana en 0 eso es
    un ZeroDivisionError en CADA request, y no es `RedisError` ni `OSError`, asi
    que no lo atrapa ni el `except` del middleware ni el de
    `enforce_rate_limit`: 500 en toda la API. La regla 17 dice que la config de
    produccion falla cerrada; sin el piso fallaba abierta y el sintoma aparecia
    en el primer request, no en el arranque.
    """
    from core.rate_limit import _hit_rate_limit

    with pytest.raises(ZeroDivisionError):
        await _hit_rate_limit("ip:1.2.3.4", "global", 10, 0)


def test_produccion_aplica_defaults_endurecidos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin declararlos, produccion no puede quedar con los valores de desarrollo."""
    endurecidos = (
        "COOKIE_SECURE",
        "EXPOSE_API_DOCS",
        "COOKIE_SAMESITE",
        "OPS_ENABLE_PUBLIC_HEALTH",
    )
    # El entorno de tests define estas variables; hay que sacarlas para observar
    # el default que aplica apply_production_defaults.
    for clave in endurecidos:
        monkeypatch.delenv(clave, raising=False)

    settings = Settings(**{k: v for k, v in BASE.items() if k not in endurecidos})
    assert settings.COOKIE_SECURE is True
    assert settings.EXPOSE_API_DOCS is False
    assert settings.COOKIE_SAMESITE == "lax"
    # AUD2-B7-12 (2026-09-20): `GET /api/ops/health/ready` devolvia a cualquier
    # anonimo `{"components": {"db": false, "redis": true}}`. nginx proxea
    # `/api/` entero, asi que el endpoint es publico, y el flag venia en True
    # por default sin que ninguna validacion de produccion lo tocara: el propio
    # comentario del endpoint reconoce que ese detalle es "info util para un
    # atacante anonimo que sondea la infra". El healthcheck del compose sondea
    # 127.0.0.1 dentro de la red interna y le alcanza con el 503.
    assert settings.OPS_ENABLE_PUBLIC_HEALTH is False
