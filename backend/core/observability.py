"""Inicializacion de Sentry para la API y los workers.

Sin esto, un webhook que falla o una tarea de Celery que revienta en produccion
pasan en silencio: nadie se entera hasta que un cliente reclama.
"""

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit, urlunsplit

import structlog

from core.config import Environment, settings

if TYPE_CHECKING:
    from sentry_sdk.types import Event, Hint, SamplingContext

logger = structlog.get_logger()

_initialized = False

# Rutas de chequeo que no aportan nada como transaccion y solo generan ruido.
_IGNORED_TRANSACTIONS = {"/ops/health/live", "/ops/health/ready"}

# F5-02 (R11-13): tasas de trazas por ruta en produccion. Health y SLO los
# consultan el compose, el uptime externo y el cron de latencia cada pocos
# segundos: como transaccion no dicen nada y agotaban la cuota. Pagos y el
# webhook de Mercado Pago se trazan enteros porque son lo que hay que poder
# reconstruir ante un reclamo.
_RATE_NEVER = 0.0
_RATE_PAYMENTS = 1.0
_RATE_PUBLIC_READ = 0.02
_RATE_WRITE = 0.2
_RATE_PANEL_READ = 0.1
# Beat dispara varias tareas por minuto; si corren o no lo cubren Sentry Crons
# (``monitor_beat_tasks``, periodos de 60 s o mas) y ``/ops/slo``, no la traza.
_RATE_TASK = 0.02
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_UNTRACED_PREFIXES = ("/ops/health/",)
_UNTRACED_PATHS = frozenset({"/ops/health", "/ops/slo"})


def _request_path(asgi_scope: dict[str, Any]) -> str:
    """Ruta de la app sin el prefijo del proxy (``root_path``) ni ``/api``."""
    path = str(asgi_scope.get("path") or "/")
    root_path = str(asgi_scope.get("root_path") or "")
    if root_path and path.startswith(root_path):
        path = path[len(root_path) :] or "/"
    if path == "/api" or path.startswith("/api/"):
        path = path[len("/api") :] or "/"
    return path


def _request_rate(method: str, path: str, *, production: bool) -> float:
    if path in _UNTRACED_PATHS or path.startswith(_UNTRACED_PREFIXES):
        return _RATE_NEVER
    if not production:
        return 1.0
    if path == "/payments" or path.startswith("/payments/"):
        return _RATE_PAYMENTS
    if method not in _READ_METHODS:
        return _RATE_WRITE
    if path.startswith("/public/"):
        return _RATE_PUBLIC_READ
    return _RATE_PANEL_READ


def _traces_sampler(sampling_context: "SamplingContext") -> float:
    """Tasa de muestreo de una transaccion (F5-02).

    Un request se decide SOLO por su ruta y metodo: el header ``sentry-trace``
    lo manda el cliente y respetarlo dejaria que cualquiera fuerce el 100 %.
    Una tarea de Celery, en cambio, hereda la decision del request que la
    encolo (el padre es nuestro), y sin padre usa la tasa de tareas.
    """
    production = settings.ENV == Environment.PRODUCTION
    asgi_scope = sampling_context.get("asgi_scope")
    if isinstance(asgi_scope, dict):
        method = str(asgi_scope.get("method") or "GET").upper()
        return _request_rate(method, _request_path(asgi_scope), production=production)
    parent = sampling_context.get("parent_sampled")
    if parent is not None:
        return 1.0 if parent else 0.0
    return _RATE_TASK if production else 1.0


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
        # PV-02: la query lleva telefonos (``deposit/preview?client_phone=``)
        # y la ruta tambien (``/public/client/{store}/{phone}/...``).
        request.pop("query_string", None)
        url = request.get("url")
        if isinstance(url, str):
            request["url"] = _mask_url(url)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for header in ("authorization", "cookie", "x-signature"):
                headers.pop(header, None)
                headers.pop(header.title(), None)

    # extra/contexts pueden traer PII o secretos si algun logger los adjunta.
    # Se recortan por clave sensible en vez de confiar en que nadie los ponga.
    extra: Any = event.get("extra")
    if isinstance(extra, dict):
        # PV-02: la integracion de Celery adjunta los argumentos de la tarea
        # que fallo; los de ``send_otp_email`` son email, asunto y el cuerpo
        # CON el codigo. El nombre de la tarea queda.
        job = extra.get("celery-job")
        if isinstance(job, dict):
            for key in ("args", "kwargs"):
                if key in job:
                    job[key] = "[redacted]"
    _scrub_mapping(extra)
    for context in (event.get("contexts") or {}).values():
        _scrub_mapping(context)
    _mask_breadcrumb_urls(event)
    _drop_frame_vars(event)
    return event


# Un segmento de ruta que, decodificado, es un telefono: 8 o mas digitos con
# los separadores habituales y un ``+`` opcional. Un ULID o un slug tienen
# letras y no entran.
_PHONE_SEGMENT = re.compile(r"\+?[\d\s\-().]{8,}")


def _mask_url(url: str) -> str:
    """URL sin query ni fragmento y con los segmentos-telefono tapados."""
    parts = urlsplit(url)
    segments = [
        "[phone]"
        if _PHONE_SEGMENT.fullmatch(unquote(segment))
        and sum(ch.isdigit() for ch in unquote(segment)) >= 8
        else segment
        for segment in parts.path.split("/")
    ]
    return urlunsplit((parts.scheme, parts.netloc, "/".join(segments), "", ""))


def _mask_breadcrumb_urls(event: "Event") -> None:
    """Las migas HTTP (``data.url``) pasan por la misma mascara que la URL."""
    breadcrumbs: Any = event.get("breadcrumbs")
    values = breadcrumbs.get("values") if isinstance(breadcrumbs, dict) else None
    for crumb in values or []:
        data = crumb.get("data") if isinstance(crumb, dict) else None
        if isinstance(data, dict) and isinstance(data.get("url"), str):
            data["url"] = _mask_url(data["url"])


def _drop_frame_vars(event: "Event") -> None:
    """Defensa en profundidad de ``include_local_variables=False`` (PV-02)."""
    exception: Any = event.get("exception")
    values = exception.get("values") if isinstance(exception, dict) else None
    for value in values or []:
        stacktrace = value.get("stacktrace") if isinstance(value, dict) else None
        frames = stacktrace.get("frames") if isinstance(stacktrace, dict) else None
        for frame in frames or []:
            if isinstance(frame, dict):
                frame.pop("vars", None)


_SENSITIVE_KEYS = (
    "password",
    "token",
    "secret",
    "authorization",
    "cookie",
    "email",
    "phone",
    "telefono",
    "access_token",
    "refresh_token",
    "api_key",
    "signature",
)


def _scrub_mapping(mapping: Any) -> None:
    """Redacta valores de claves sensibles en un dict (recursivo, en sitio)."""
    if not isinstance(mapping, dict):
        return
    for key, value in list(mapping.items()):
        if isinstance(key, str) and any(s in key.lower() for s in _SENSITIVE_KEYS):
            mapping[key] = "[redacted]"
        elif isinstance(value, dict):
            _scrub_mapping(value)


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

    from sentry_sdk.integrations.celery import CeleryIntegration

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=str(getattr(settings.ENV, "value", settings.ENV)),
        # ``VERSION`` sale de ``APP_VERSION`` (compose, bloque
        # ``x-app-environment``): el tag de la imagen desplegada, no el 0.1.0
        # fijo del default. Asi un error se ata al release que lo introdujo.
        release=settings.VERSION,
        # F5-02: tasa por ruta; fuera de produccion se ve todo menos health.
        traces_sampler=_traces_sampler,
        # Sentry Crons: las tareas de beat con periodo de un minuto o mas
        # reportan inicio y fin, y una que deja de correr (beat caido, worker
        # trabado) avisa sola; son un monitor cada una (cuota del plan de
        # Sentry, decision del dueno; ``exclude_beat_tasks`` saca las que no
        # hagan falta). El SDK saltea los intervalos de menos de 60 s: el
        # outbox (cada 20 s) no tiene monitor y su atraso lo cubre
        # ``/ops/slo`` (``oldest_pending_*``).
        integrations=[CeleryIntegration(monitor_beat_tasks=True)],
        # Nunca mandamos PII: los turnos llevan nombre, telefono y email.
        send_default_pii=False,
        # PV-02: sin esto cada frame viajaba con sus variables locales (p. ej.
        # el payload de la reserva con nombre, telefono y email).
        include_local_variables=False,
        before_send=_scrub_event,
        # ``before_send`` no corre sobre transacciones: sin esto el 10 %
        # muestreado salia con ``request.url``, la query y las migas crudas.
        before_send_transaction=_scrub_event,
    )
    sentry_sdk.set_tag("component", component)
    _initialized = True
    logger.info("sentry_initialized", component=component)
    return True


def report_exception(exc: BaseException, **context: Any) -> None:
    """Manda una excepcion tragada a Sentry, con contexto y sin poder romper.

    Para los caminos best-effort: lo que se decide seguir pese al error igual
    tiene que dejar un evento investigable, porque el log estructurado del
    contenedor se rota y nadie lo mira (AUD2-B7-03, 2026-09-20). Si Sentry no
    esta inicializado, ``capture_exception`` no hace nada; si el reporte
    mismo falla, se registra y se sigue: reportar un problema no puede
    convertirse en uno.
    """
    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - dependencia opcional
        return
    try:
        # Scope propio: el contexto extra no se pega a los eventos siguientes.
        with sentry_sdk.new_scope() as scope:
            if context:
                scope.set_context("shifty", dict(context))
            sentry_sdk.capture_exception(exc)
    except Exception:  # pragma: no cover - Sentry nunca rompe el camino
        logger.warning("sentry_capture_failed", exc_info=True)


__all__ = ["init_observability", "report_exception"]
