"""Inicializacion de Sentry para la API y los workers.

Sin esto, un webhook que falla o una tarea de Celery que revienta en produccion
pasan en silencio: nadie se entera hasta que un cliente reclama.
"""

from typing import TYPE_CHECKING, Any

import structlog

from core.config import Environment, settings

if TYPE_CHECKING:
    from sentry_sdk.types import Event, Hint

logger = structlog.get_logger()

_initialized = False

# Rutas de chequeo que no aportan nada como transaccion y solo generan ruido.
_IGNORED_TRANSACTIONS = {"/ops/health/live", "/ops/health/ready"}


def _scrub_event(event: "Event", _hint: "Hint") -> "Event | None":
    """Descarta ruido y evita mandar secretos o datos de clientes a Sentry."""
    transaction = event.get("transaction")
    if transaction in _IGNORED_TRANSACTIONS:
        return None

    request: Any = event.get("request")
    if isinstance(request, dict):
        # El body puede traer passwords, tokens OAuth o datos personales.
        request.pop("data", None)
        request.pop("cookies", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for header in ("authorization", "cookie", "x-signature"):
                headers.pop(header, None)
                headers.pop(header.title(), None)
    return event


def init_observability(component: str) -> bool:
    """Arranca Sentry si hay DSN configurado. Devuelve si quedo activo."""
    global _initialized
    if _initialized or not settings.SENTRY_DSN:
        return _initialized

    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - dependencia opcional
        logger.warning("sentry_sdk_missing", component=component)
        return False

    is_production = settings.ENV == Environment.PRODUCTION
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=str(getattr(settings.ENV, "value", settings.ENV)),
        release=settings.VERSION,
        # En produccion se muestrea para no saturar la cuota; fuera de ella
        # conviene ver todo mientras se depura.
        traces_sample_rate=0.1 if is_production else 1.0,
        # Nunca mandamos PII: los turnos llevan nombre, telefono y email.
        send_default_pii=False,
        before_send=_scrub_event,
    )
    sentry_sdk.set_tag("component", component)
    _initialized = True
    logger.info("sentry_initialized", component=component)
    return True


__all__ = ["init_observability"]
