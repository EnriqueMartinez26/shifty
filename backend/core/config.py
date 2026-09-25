import os
import re
import secrets
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import AliasChoices, Field, model_validator
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


# Marcadores tipicos de los placeholders del repo (.env.example, plantillas).
# Un secreto que los contenga NO fue reemplazado por uno real.
_PLACEHOLDER_MARKERS = (
    "replace",
    "change_this",
    "change-me",
    "changeme",
    "placeholder",
    "at_least_32",
    "minimum_secret",
    "your_secret",
    "example",
    "generate_a_very_secret",
    "xxxx",
)


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


# Minimos operativos: valen en TODO entorno, desarrollo incluido, porque un
# valor absurdo aca no es una configuracion insegura sino un proceso que no
# funciona. Tabla `(campo, minimo, mensaje)` y no trece `if` identicos: sumar
# un limite es sumar una fila, con el mensaje al lado del numero que justifica.
# El minimo es float porque los timeouts de Redis lo son; un int entra igual.
_MINIMOS_OPERATIVOS: tuple[tuple[str, float, str], ...] = (
    (
        "PAYMENTS_CIRCUIT_BREAKER_FAILURE_THRESHOLD",
        1,
        "PAYMENTS_CIRCUIT_BREAKER_FAILURE_THRESHOLD debe ser >= 1",
    ),
    (
        "PAYMENTS_CIRCUIT_BREAKER_RECOVERY_SECONDS",
        1,
        "PAYMENTS_CIRCUIT_BREAKER_RECOVERY_SECONDS debe ser >= 1",
    ),
    (
        "MERCADOPAGO_OAUTH_STATE_TTL_SECONDS",
        60,
        "MERCADOPAGO_OAUTH_STATE_TTL_SECONDS debe ser >= 60",
    ),
    (
        "MERCADOPAGO_WEBHOOK_MAX_AGE_SECONDS",
        60,
        "MERCADOPAGO_WEBHOOK_MAX_AGE_SECONDS debe ser >= 60",
    ),
    ("PAYMENT_HOLD_MINUTES", 5, "PAYMENT_HOLD_MINUTES debe ser >= 5"),
    ("REDIS_MAX_CONNECTIONS", 1, "REDIS_MAX_CONNECTIONS debe ser >= 1"),
    (
        "CELERY_WORKER_PREFETCH_MULTIPLIER",
        1,
        "CELERY_WORKER_PREFETCH_MULTIPLIER debe ser >= 1",
    ),
    (
        "CELERY_TASK_SOFT_TIME_LIMIT_SECONDS",
        1,
        "CELERY_TASK_SOFT_TIME_LIMIT_SECONDS debe ser >= 1",
    ),
    (
        "MAX_REQUEST_BODY_BYTES",
        1024,
        "MAX_REQUEST_BODY_BYTES no puede ser menor a 1024 bytes",
    ),
    # `_hit_rate_limit` hace `now // window_seconds`: con 0 es un
    # ZeroDivisionError en CADA request, y no es RedisError ni OSError, asi que
    # no lo atrapa ningun `except` del modulo (AUD2-B7-06, 2026-09-20).
    (
        "RATE_LIMIT_WINDOW_SECONDS",
        1,
        "RATE_LIMIT_WINDOW_SECONDS debe ser >= 1",
    ),
    # Hermano de MAX_REQUEST_BODY_BYTES: tambien necesita piso, o la subida de
    # logo/portada queda inutilizable sin que el arranque diga nada.
    (
        "MAX_UPLOAD_BODY_BYTES",
        1024,
        "MAX_UPLOAD_BODY_BYTES no puede ser menor a 1024 bytes",
    ),
    # Retencion (F1-19): una ventana en 0 borraria todo lo procesado HOY, y
    # un lote en 0 no avanza nunca. Un typo en el .env no puede ser una purga.
    (
        "RETENTION_OUTBOX_PROCESSED_DAYS",
        1,
        "RETENTION_OUTBOX_PROCESSED_DAYS debe ser >= 1",
    ),
    (
        "RETENTION_INBOX_PROCESSED_DAYS",
        1,
        "RETENTION_INBOX_PROCESSED_DAYS debe ser >= 1",
    ),
    ("RETENTION_OTP_EXPIRED_DAYS", 1, "RETENTION_OTP_EXPIRED_DAYS debe ser >= 1"),
    (
        "RETENTION_NOTIFICATIONS_READ_DAYS",
        1,
        "RETENTION_NOTIFICATIONS_READ_DAYS debe ser >= 1",
    ),
    ("RETENTION_BATCH_SIZE", 1, "RETENTION_BATCH_SIZE debe ser >= 1"),
    ("RETENTION_DEAD_LETTER_DAYS", 1, "RETENTION_DEAD_LETTER_DAYS debe ser >= 1"),
    # Un timeout en 0 no significa "sin espera": redis-py lo toma como no
    # bloqueante y toda operacion falla.
    (
        "REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",
        0.1,
        "REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS debe ser >= 0.1",
    ),
    (
        "REDIS_SOCKET_TIMEOUT_SECONDS",
        0.1,
        "REDIS_SOCKET_TIMEOUT_SECONDS debe ser >= 0.1",
    ),
)

# Interruptores que produccion exige en una posicion y no en la otra:
# `(campo, valor obligatorio, mensaje)`.
_BOOLEANOS_DE_PRODUCCION: tuple[tuple[str, bool, str], ...] = (
    (
        "RATE_LIMIT_FAIL_CLOSED",
        True,
        "RATE_LIMIT_FAIL_CLOSED debe ser true en produccion: sin Redis "
        "no puede quedar todo sin limite",
    ),
    ("EXPOSE_API_DOCS", False, "EXPOSE_API_DOCS debe ser false en produccion"),
    ("RATE_LIMIT_ENABLED", True, "RATE_LIMIT_ENABLED debe estar activo en produccion"),
    ("COOKIE_SECURE", True, "COOKIE_SECURE debe ser true en produccion"),
    (
        "OTP_DEBUG_EXPOSE_CODE",
        False,
        "OTP_DEBUG_EXPOSE_CODE debe ser false en produccion",
    ),
    # `GET /api/ops/health/ready` devolvia a cualquier anonimo el detalle por
    # componente (`{"db": false, "redis": true}`) y nginx proxea `/api/`
    # entero, asi que es publico. El propio comentario del endpoint reconoce
    # que eso es "info util para un atacante anonimo que sondea la infra" y por
    # eso lo puso detras de un flag... que venia abierto y que ninguna
    # validacion de produccion miraba (AUD2-B7-12, 2026-09-20). El healthcheck
    # del compose sondea 127.0.0.1 dentro de la red interna y le alcanza con el
    # 503; el detalle se mira con `docker compose logs`, no desde afuera.
    (
        "OPS_ENABLE_PUBLIC_HEALTH",
        False,
        "OPS_ENABLE_PUBLIC_HEALTH debe ser false en produccion",
    ),
)

# Una URL publica que apunte a la maquina del deploy deja los mails y los
# retornos de Mercado Pago apuntando a ningun lado.
_PREFIJOS_LOCALES = ("http://localhost", "http://127.0.0.1")

# Unica API de Mercado Pago que se acepta fuera de desarrollo (regla 17): otra
# base mandaria access tokens de las tiendas a un host ajeno.
MERCADOPAGO_API_BASE_URL_REAL = "https://api.mercadopago.com"
# Version de un texto legal: corta y sin espacios ("2026-09-25", "v2.1").
LEGAL_VERSION_PATTERN = r"^[A-Za-z0-9._-]{1,20}$"


class Settings(BaseSettings):
    PROJECT_NAME: str = "Shifty"
    VERSION: str = "0.1.0"
    # Nivel de los logs JSON de la app (core/logging.py, F0-22). Un valor
    # fuera de la lista no valida: el proceso no arranca con un nivel que no
    # entiende (regla 21).
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
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
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    FIELD_ENCRYPTION_KEY: str | None = None
    OTP_CODE_EXPIRE_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5
    # Tope acumulado de VERIFICACIONES por telefono (ventana 1h), exitosas o
    # no: se consume antes de comparar el codigo. Pedir codigos nuevos no
    # resetea el presupuesto. B4-09 (2026-09-18): antes se llamaba
    # OTP_MAX_FAILURES_PER_HOUR, que prometia "fallos"; el nombre viejo sigue
    # aceptado como alias para que un .env existente no se ignore en silencio.
    OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR: int = Field(
        default=10,
        validation_alias=AliasChoices(
            "OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR", "OTP_MAX_FAILURES_PER_HOUR"
        ),
    )
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
    # Presupuesto TOTAL de un request para hablar con Mercado Pago (preferencia
    # + refresh OAuth + reintento), no por llamada. Tiene que quedar debajo de
    # los 30 s de nginx con margen para la base, la compensacion y el mail en
    # linea: por encima el cliente ve 504 con la reserva ya commiteada (F1-04,
    # R8-01, R11-08). 8 s: una preferencia tarda 1-2 s y la reserva tiene que
    # contestar en menos de 10 s aun con MP degradado (flujo (j) de
    # tests/e2e); lo que no entra se compensa y el cliente reintenta.
    MERCADOPAGO_REQUEST_BUDGET_SECONDS: float = Field(default=8.0, gt=0, lt=25)
    # Base de la API de Mercado Pago. Configurable SOLO para apuntar al
    # emulador de tests/e2e en desarrollo; staging y produccion exigen la real.
    MERCADOPAGO_API_BASE_URL: str = MERCADOPAGO_API_BASE_URL_REAL
    # Nonce propio en la ``external_reference`` de cada link NUEVO
    # (``<turno>:<link_ref>``; revision de perf/f4-pay, 2026-09-25): un pago de
    # un link reemplazado deja de pasar la integridad aunque MP no mande
    # ``preference_id``. Prendido por defecto: Shifty nunca estuvo en
    # produccion, no hay links legados en vuelo (correccion del coordinador).
    # Apagarlo solo sirve para volver a un codigo anterior a este release, que
    # no entiende el nonce; apagado, regenerar el link de un cobro vencido
    # responde 409 (sin nonce no se distingue un pago del link viejo) y los
    # links con nonce siguen matcheando (docs/DEPLOY_RUNBOOK.md, seccion 5).
    MERCADOPAGO_LINK_REF_ENABLED: bool = True
    # Minutos que un turno queda reservado esperando el pago de la seña. Al
    # vencer, el slot vuelve a estar disponible para otro cliente.
    PAYMENT_HOLD_MINUTES: int = 30
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_WHATSAPP_FROM: str | None = None
    EXPOSE_API_DOCS: bool = True
    MAX_REQUEST_BODY_BYTES: int = 32 * 1024
    # Limite mayor SOLO para las rutas de subida de imagenes (logo/portada), que
    # aceptan multipart. El resto sigue con el tope de 32KB.
    MAX_UPLOAD_BODY_BYTES: int = 3 * 1024 * 1024
    # Solo JSON: la API no tiene endpoints con formularios, y aceptar
    # x-www-form-urlencoded habilitaba CSRF via <form> cross-site (los POST de
    # formulario son "simple requests" y no pasan por preflight de CORS).
    # Excepcion acotada: las rutas de subida de imagenes aceptan multipart (van
    # con Bearer, no cookie, asi que no son alcanzables por CSRF de formulario).
    ALLOWED_WRITE_CONTENT_TYPES: str = "application/json"
    TRUST_PROXY_HEADERS: bool = True
    RATE_LIMIT_ENABLED: bool = True
    # Con Redis caido, responder 503 en vez de dejar pasar sin limite, PERO
    # solo en las politicas que frenan fuerza bruta y abuso anonimo: ``auth``,
    # ``public-write`` y ``otp`` (``core.rate_limit.FAIL_CLOSED_POLICIES``),
    # mas el presupuesto de OTP por telefono y el lockout de login. Lectura
    # publica, ``global`` (panel, ops) y el webhook de Mercado Pago fallan
    # abierto con aviso (F1-09, decision 9 del dueno, 2026-09-24): antes el
    # flag cerraba toda la API y Redis era punto unico de falla. Produccion
    # lo exige en true (regla 17).
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
    # Minutos que un cupo liberado se ofrece a UNA persona de la lista de
    # espera antes de pasar a la siguiente (exclusividad blanda).
    WAITLIST_OFFER_MINUTES: int = 10
    # Detalle por componente en el readiness publico. Abierto en desarrollo
    # (diagnosticar es lo que se hace ahi) y cerrado en produccion, donde lo
    # exige `_BOOLEANOS_DE_PRODUCCION` (AUD2-B7-12).
    OPS_ENABLE_PUBLIC_HEALTH: bool = True
    SLO_MAX_PENDING_WEBHOOKS: int = 200
    SLO_MAX_FAILED_WEBHOOKS: int = 20
    # Webhooks que agotaron sus reintentos en las ultimas 24 h: cualquiera es
    # un cobro sin aplicar (revision de perf/f4-pay).
    SLO_MAX_DEAD_LETTER_WEBHOOKS_24H: int = 0
    SLO_MAX_PENDING_OUTBOX: int = 200
    # Atraso tolerado (F1-25, R9-16): el outbox corre cada 20 s y el inbox
    # cada minuto, con reintento a los 15 s tras un webhook fallido. Un mail
    # (fila email.send, F2-03) diferido mas de 3 minutos ya es una alerta.
    SLO_MAX_OLDEST_PENDING_OUTBOX_SECONDS: int = 180
    SLO_MAX_OLDEST_PENDING_INBOX_SECONDS: int = 300
    SLO_MAX_OLDEST_PENDING_EMAIL_SEND_SECONDS: int = 180
    # Edad minima de un cobro pendiente para que la conciliacion le pregunte a
    # Mercado Pago (F1-20, decision 20): antes de eso el cliente sigue en el
    # checkout y la consulta solo gasta la corrida.
    RECONCILIATION_MIN_AGE_MINUTES: int = 10
    # Retencion (F1-19, decision 17 del dueno): purga diaria por lotes de lo
    # ya procesado/vencido/leido. audit_logs no se purga nunca. Con
    # RETENTION_DRY_RUN la tarea solo cuenta (modules/housekeeping/retention.py).
    RETENTION_OUTBOX_PROCESSED_DAYS: int = 90
    RETENTION_INBOX_PROCESSED_DAYS: int = 90
    RETENTION_OTP_EXPIRED_DAYS: int = 7
    RETENTION_NOTIFICATIONS_READ_DAYS: int = 180
    RETENTION_BATCH_SIZE: int = 5000
    # Outbox/inbox con error (dead letter, nunca aplicados): evidencia de
    # disputa, se conservan un ano (revision de f2b, decision delegada).
    RETENTION_DEAD_LETTER_DAYS: int = 365
    RETENTION_DRY_RUN: bool = False
    MERCADOPAGO_WEBHOOK_SECRET: str | None = None

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
    # Redis del cache de disponibilidad (F0-15): `volatile-ttl`, sin persistencia.
    # Vacio = el mismo REDIS_URL (compatibilidad con un deploy de un solo Redis).
    # Nada que sea estado (rate limit, idempotencia, lockout, OTP) va aca.
    REDIS_CACHE_URL: str | None = None
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

    # Versiones vigentes de los textos legales (PV-09, L1 O-3/O-4, 2026-09-25).
    # El portal las lee de ``GET /public/legal/versions`` y las manda con la
    # aceptacion; quedan en el turno y en la entrada de la lista de espera.
    # ``STORE_TERMS_VERSION``: terminos B2B que acepta el admin de la tienda
    # (``/stores/me/terms-acceptance``). Cambiar un texto es subir su version.
    LEGAL_TERMS_VERSION: str = Field(
        default="2026-09-25", pattern=LEGAL_VERSION_PATTERN
    )
    LEGAL_PRIVACY_VERSION: str = Field(
        default="2026-09-25", pattern=LEGAL_VERSION_PATTERN
    )
    STORE_TERMS_VERSION: str = Field(
        default="2026-09-25", pattern=LEGAL_VERSION_PATTERN
    )
    # Anotarse en la lista de espera EXIGE ``accepts_terms`` y las versiones
    # solo con este flag. Apagado hasta que el front tenga la casilla: el
    # front actual no manda el campo y se romperia.
    LEGAL_WAITLIST_CONSENT_REQUIRED: bool = False

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
        production_data.setdefault("COOKIE_SECURE", True)
        # Lax y no None: la cookie es credencial y SameSite=None la mandaba en
        # requests cross-site (CSRF). El frontend comparte site via nginx.
        production_data.setdefault("COOKIE_SAMESITE", "lax")
        production_data.setdefault("EXPOSE_API_DOCS", False)
        production_data.setdefault("RATE_LIMIT_FAIL_CLOSED", True)
        production_data.setdefault("OPS_ENABLE_PUBLIC_HEALTH", False)
        return production_data

    def _validate_secrets_outside_development(self) -> None:
        """Secretos y destino de los tokens de MP: todo entorno menos desarrollo.

        Un staging que firme con el placeholder del repo emite tokens
        forjables contra datos reales, asi que la vara no es solo produccion.
        """
        if (
            self.SECRET_KEY == "generate_a_very_secret_key_here_for_production"
            or len(self.SECRET_KEY) < 32
            or _looks_like_placeholder(self.SECRET_KEY)
        ):
            raise ValueError(
                "SECRET_KEY debe ser fuerte y unico fuera de desarrollo "
                "(parece un placeholder del repo)"
            )
        # Misma vara para la clave de cifrado de campos: un placeholder deja
        # el cifrado de los tokens de MP como un no-op reversible.
        if self.FIELD_ENCRYPTION_KEY and _looks_like_placeholder(
            self.FIELD_ENCRYPTION_KEY
        ):
            raise ValueError("FIELD_ENCRYPTION_KEY parece un placeholder del repo")
        # Mismo alcance que los secretos: staging tambien tiene tokens reales
        # de MP y no puede mandarlos a otro host (el emulador es de desarrollo).
        if self.MERCADOPAGO_API_BASE_URL != MERCADOPAGO_API_BASE_URL_REAL:
            raise ValueError(
                "MERCADOPAGO_API_BASE_URL debe ser https://api.mercadopago.com fuera de "
                "desarrollo"
            )

    def _validate_production_origins(self) -> None:
        """Produccion: origenes y URLs publicas que no pueden ser locales."""
        if "localhost" in self.CORS_ORIGINS or "127.0.0.1" in self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS no debe incluir localhost en produccion")
        if "*" in self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS no puede ser * con credenciales habilitadas")
        # Los dos mensajes van escritos enteros y no con un f-string sobre el
        # nombre del campo: el texto exacto es lo que se busca en el log y lo
        # que inventaria el test de alcances.
        if self.FRONTEND_URL.startswith(_PREFIJOS_LOCALES):
            raise ValueError("FRONTEND_URL no puede apuntar a localhost en produccion")
        if self.PUBLIC_API_URL.startswith(_PREFIJOS_LOCALES):
            raise ValueError(
                "PUBLIC_API_URL no puede apuntar a localhost en produccion"
            )

    def _validate_production_hardening(self) -> None:
        """Produccion: interruptores, sesiones, OTP y clave de cifrado."""
        for field, required, message in _BOOLEANOS_DE_PRODUCCION:
            if getattr(self, field) is not required:
                raise ValueError(message)
        if self.ACCESS_TOKEN_EXPIRE_MINUTES > 30:
            raise ValueError(
                "ACCESS_TOKEN_EXPIRE_MINUTES no debe superar 30 en produccion"
            )
        if (
            self.FIELD_ENCRYPTION_KEY is not None
            and len(self.FIELD_ENCRYPTION_KEY) < 32
        ):
            raise ValueError(
                "FIELD_ENCRYPTION_KEY debe tener al menos 32 caracteres en produccion"
            )
        if self.OTP_PROVIDER == "console":
            raise ValueError("OTP_PROVIDER no puede ser console en produccion")
        if self.COOKIE_SAMESITE.lower() not in {"lax", "strict", "none"}:
            raise ValueError("COOKIE_SAMESITE debe ser lax, strict o none")
        if not self.FIELD_ENCRYPTION_KEY:
            raise ValueError("FIELD_ENCRYPTION_KEY es obligatorio en produccion")

    def _validate_operational_limits(self) -> None:
        """Limites que valen en cualquier entorno, desarrollo incluido."""
        for field, minimum, message in _MINIMOS_OPERATIVOS:
            if getattr(self, field) < minimum:
                raise ValueError(message)
        # Los dos que no son un minimo fijo: una relacion entre dos campos y un
        # techo, asi que no entran en la tabla.
        if (
            self.CELERY_TASK_TIME_LIMIT_SECONDS
            <= self.CELERY_TASK_SOFT_TIME_LIMIT_SECONDS
        ):
            raise ValueError(
                "CELERY_TASK_TIME_LIMIT_SECONDS debe ser mayor al soft time limit"
            )
        if self.MAX_REQUEST_BODY_BYTES > 1024 * 1024:
            raise ValueError(
                "MAX_REQUEST_BODY_BYTES no debe superar 1MB sin revision de seguridad"
            )

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Config que falla cerrada (regla 17), repartida por alcance.

        Las 27 condiciones pertenecen a tres alcances con condiciones de entrada
        distintas; apiladas en un solo cuerpo de 94 lineas habia que leerlas
        todas para saber donde iba una nueva (B7-06). Produccion se reparte en
        dos partes para que ninguna pase de 30 lineas. Cada `raise` sigue siendo
        el mismo `ValueError` con el mismo texto, que es lo que verifican
        `tests/unit/test_config_production_guards.py` y
        `tests/unit/test_validador_de_produccion_por_alcance.py`.
        """
        if self.ENV != Environment.DEVELOPMENT:
            self._validate_secrets_outside_development()
        if self.ENV == Environment.PRODUCTION:
            self._validate_production_origins()
            self._validate_production_hardening()
        self._validate_operational_limits()
        return self

    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


_ESQUEMA = r"([a-zA-Z][a-zA-Z0-9+.-]*://)"
_URL_ENTERA = re.compile(_ESQUEMA + r"[^\s]+")
# Del esquema hasta el ULTIMO `@` del token: una contrasena generada puede
# traer `/`, `+` o `@` sin escapar, y cortar en el primero de ellos dejaba el
# resto de la contrasena afuera (o la URL entera, si el corte caia antes del
# `@`: rechazo V-diff de S-01, 2026-09-18). Peca por tapar de mas: si la ruta
# o la query traen otro `@`, se tapa tambien el host.
_CREDENCIALES_DE_URL = re.compile(_ESQUEMA + r"[^\s]*@")
_DESDE_EL_ESQUEMA_HASTA_EL_FINAL = re.compile(_ESQUEMA + r".*", re.DOTALL)
_MARCA = "[redacted]"


def _queda_un_arroba_tras_un_esquema(value: str) -> bool:
    sin_marcas = value.replace(_MARCA + "@", "")
    esquema = re.search(_ESQUEMA, sin_marcas)
    return esquema is not None and "@" in sin_marcas[esquema.end() :]


def redact_url(value: str, *, keep_target: bool = False) -> str:
    """Unica redaccion de URLs con credenciales del repo (S-01).

    Una ``DATABASE_URL`` lleva ``usuario:contraseña@host``; ningun mensaje de
    error ni log la cruza entera (regla 20). Dos niveles, un solo helper:

    * ``keep_target=True`` (scripts y migraciones): tapa ``usuario:contraseña``
      y deja esquema, host, puerto y base, que es lo que hace falta para saber
      contra que deploy se estaba apuntando.
    * por defecto (error de settings): tapa todo lo que sigue al esquema. Ese
      texto sale en el 503 publico de arranque, donde tampoco va el hostname
      interno.

    Red de seguridad para los dos: si despues de redactar todavia queda un
    `@` detras de un esquema (una contrasena con un espacio parte la URL en
    dos tokens), no se sabe donde terminan las credenciales y se tapa desde
    el esquema hasta el final del texto. Se pierde el destino, nunca un
    pedazo de la contrasena.
    """
    if keep_target:
        redactada = _CREDENCIALES_DE_URL.sub(r"\1" + _MARCA + "@", value)
    else:
        redactada = _URL_ENTERA.sub(r"\1" + _MARCA, value)
    if _queda_un_arroba_tras_un_esquema(redactada):
        return _DESDE_EL_ESQUEMA_HASTA_EL_FINAL.sub(r"\1" + _MARCA, value)
    return redactada


# Modos TLS que entienden a la vez asyncpg (`ssl=`) y psycopg2/libpq
# (`sslmode=`). Cualquier otro valor es un error, no se adivina.
_SSL_MODES = frozenset(
    {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
)
# Sin nada en la URL, la migracion exige TLS: una base administrada lo tiene y
# el entorno local/CI lo apaga explicito con `?ssl=disable`.
DEFAULT_SSL_MODE = "require"


def parse_db_url(url: str, *, label: str = "DATABASE_URL") -> dict[str, Any]:
    """Componentes de conexion para migrar con psycopg2 (B7-11, S-10).

    Unica lectura del repo: la usan `run_migrations.py` y `alembic/env.py`,
    que antes tenian cada uno su copia con otro `sslmode` por defecto
    (`require` y `disable`). Las URLs del repo son de asyncpg, cuyo parametro
    es `ssl` (`sslmode=` en esa URL rompe el engine de la API); se lee `ssl`,
    se acepta `sslmode` por compatibilidad y, si falta, `require`. La URL de
    produccion de ejemplo (`?ssl=require`) antes se ignoraba y Alembic migraba
    sin TLS.

    Ningun error lleva usuario ni contrasena (regla 20): la URL sale por
    `redact_url(..., keep_target=True)`.
    """
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.scheme != "postgresql" or not parsed.hostname or not parsed.path:
        raise ValueError(
            f"No se pudo parsear {label}: {redact_url(url, keep_target=True)}"
        )

    query = parse_qs(parsed.query)
    pedidos = {query[clave][0] for clave in ("ssl", "sslmode") if query.get(clave)}
    if len(pedidos) > 1:
        raise ValueError(
            f"{label} pide dos modos TLS distintos (ssl y sslmode): "
            f"{redact_url(url, keep_target=True)}"
        )
    sslmode = pedidos.pop() if pedidos else DEFAULT_SSL_MODE
    if sslmode not in _SSL_MODES:
        raise ValueError(
            f"{label} trae un modo TLS invalido ({sslmode!r}): "
            f"{redact_url(url, keep_target=True)}"
        )
    return {
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "host": parsed.hostname,
        "port": int(parsed.port or 5432),
        "dbname": parsed.path.lstrip("/"),
        "sslmode": sslmode,
    }


def _sanitize_settings_error(value: str) -> str:
    value = redact_url(value)
    value = re.sub(
        r"(?i)(secret|token|password|pass|key)=([^\s,;]+)", r"\1=[redacted]", value
    )
    return value[:2000]


def _fallback_settings() -> Settings:
    """Settings de respaldo cuando la configuracion real no valida.

    ``model_construct`` completa con el default de ``Settings`` todo campo que
    no se le pasa, asi que aca van SOLO tres cosas: los campos obligatorios
    (sin default en la clase), los endurecimientos deliberados del respaldo y
    lo que se lee del entorno para que el 503 salga con las URLs del deploy.
    Repetir un default aca es una segunda tabla que nadie mantiene (B7-05);
    ``tests/unit/test_fallback_settings_hereda_defaults.py`` lo vigila.

    Como ``model_construct`` saltea los validadores, este objeto puede ser
    invalido a proposito: solo sirve para que ``BootErrorMiddleware`` responda
    503 y para que Celery aborte, nunca para atender trafico.
    """
    return Settings.model_construct(
        # Obligatorios: sin ellos el atributo directamente no existe.
        # Aleatorio por proceso: aunque el BootErrorMiddleware responda 503 a
        # todo, ningun componente (Celery, scripts) debe poder firmar tokens
        # con un secreto conocido publicado en el repo.
        SECRET_KEY="boot-failed-" + secrets.token_urlsafe(32),
        DATABASE_URL="postgresql+asyncpg://invalid:invalid@localhost/invalid",
        REDIS_URL="redis://localhost:6379/0",
        SMTP_HOST="placeholder",
        SMTP_PORT=587,
        SMTP_USER="placeholder",
        SMTP_PASS="placeholder",
        EMAILS_FROM_EMAIL="no-reply@example.com",
        # Endurecimientos del respaldo: difieren a proposito del default de la
        # clase (docs apagados, sin rate limit contra un Redis que quiza no
        # esta, cookie segura, clave de cifrado desconocida en vez de None).
        COOKIE_SECURE=True,
        EXPOSE_API_DOCS=False,
        RATE_LIMIT_ENABLED=False,
        FIELD_ENCRYPTION_KEY="boot-failed-" + secrets.token_urlsafe(32),
        # Del entorno: el 503 y CORS tienen que salir con las URLs del deploy.
        FRONTEND_URL=os.getenv("FRONTEND_URL", "http://localhost:3000"),
        PUBLIC_API_URL=os.getenv("PUBLIC_API_URL", "http://localhost/api"),
        CORS_ORIGINS=os.getenv(
            "CORS_ORIGINS",
            "http://localhost,http://127.0.0.1,http://localhost:5173,http://127.0.0.1:5173",
        ),
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
