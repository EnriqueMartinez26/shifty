from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, status
from fastapi.responses import JSONResponse
from core.router import CanonicalAPIRouter
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import PermissionDeniedException

import core.database
import core.redis
from core.config import settings
from core.database import get_db
from core.responses import error_response
from core.roles import (
    ROLE_SUPER_ADMIN,
    STORE_MANAGERS,
    canonical_role,
    has_any_role,
    store_scope_for,
)
from core.utils import ensure_utc_aware
from modules.auth.dependencies import get_current_user
from modules.payments.jobs import EVENT_EMAIL_SEND
from modules.payments.model import (
    WEBHOOK_INBOX_MAX_ATTEMPTS,
    OutboxMessage,
    WebhookInbox,
)
from modules.stores.model import Store
from modules.users.model import User

router = CanonicalAPIRouter(prefix="/ops", tags=["Operations"])


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    if not settings.OPS_ENABLE_PUBLIC_HEALTH:
        return {"status": "disabled"}
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


# Tope de cada chequeo de readiness (B5-17). Sin el, asyncpg espera hasta 60 s
# la conexion (mas el pool_timeout), SELECT 1 hasta el statement_timeout y
# Redis reintenta: el curl del healthcheck (--max-time 4) cortaba la sonda
# pero la corrutina quedaba colgada en el servidor. 2 s por componente, en
# paralelo, deja la respuesta por debajo de ese --max-time.
READINESS_CHECK_TIMEOUT_SECONDS = 2.0


async def _database_ready() -> bool:
    """``SELECT 1`` con sesion propia, abierta DENTRO del try.

    No usa ``Depends(get_db)``: esa dependencia abre la conexion (contexto de
    tenant) antes del endpoint, y con Postgres caido la respuesta era un 500
    que nunca llegaba al 503. ``SELECT 1`` no toca tablas: no necesita tenant.
    """
    try:
        async with asyncio.timeout(READINESS_CHECK_TIMEOUT_SECONDS):
            async with core.database.SessionLocal() as session:
                await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _redis_ready() -> bool:
    """``PING`` a los DOS Redis (F0-15), clientes obtenidos DENTRO del try.

    El de estado sostiene rate limit, idempotencia y lockout; el de cache, la
    disponibilidad publica, que con ese Redis caido falla. Cualquiera de los
    dos caido es una instancia que no esta lista. Sin ``REDIS_CACHE_URL`` los
    dos son el mismo cliente y el segundo ping es redundante pero inocuo.
    """
    try:
        async with asyncio.timeout(READINESS_CHECK_TIMEOUT_SECONDS):
            estado = await core.redis.get_redis()
            cache = await core.redis.get_availability_cache()
            await asyncio.gather(estado.ping(), cache.ping())
        return True
    except Exception:
        return False


@router.get("/health/ready", response_model=None)
async def readiness() -> dict[str, object] | JSONResponse:
    now = datetime.now(timezone.utc).isoformat()
    db_ok, redis_ok = await asyncio.gather(_database_ready(), _redis_ready())

    status_value = "ok" if db_ok and redis_ok else "degraded"

    # Con el flag apagado se devuelve SOLO el estado agregado: ni el detalle de
    # componentes ni -antes- el nombre de clase de la excepcion (info util para
    # un atacante anonimo que sondea la infra). El nombre de clase se elimino en
    # ambos casos.
    body: dict[str, object] = {"status": status_value, "time": now}
    if settings.OPS_ENABLE_PUBLIC_HEALTH:
        body["components"] = {"db": db_ok, "redis": redis_ok}

    # B5-17: el estado de salud ES el codigo HTTP. Con 200 + "degraded" nada
    # podia sacar la instancia de rotacion; el healthcheck del backend en
    # docker-compose.yml (curl -f) depende de este 503. El cuerpo va en la
    # forma canonica de error, con el mismo detalle que antes y sin excepcion.
    if status_value != "ok":
        return error_response(
            "SERVICE_NOT_READY",
            "El servicio no esta listo",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=body,
        )
    return body


def _segundos_desde(ahora: datetime, desde: datetime | None) -> int:
    """Antiguedad en segundos enteros; 0 si no hay pendiente."""
    if desde is None:
        return 0
    return max(0, int((ahora - ensure_utc_aware(desde)).total_seconds()))


async def _slo_metrics(db: AsyncSession, store_id: str | None) -> dict[str, int]:
    """Colas y atraso del inbox y del outbox; ``None`` = global.

    UNA sentencia agregada por tabla (regla 11; F1-25, R9-16): los contadores
    solos no distinguian un outbox al dia de uno que despacha con minutos de
    atraso. Desde F2-03 un mail que el presupuesto del despacho no alcanza
    queda como fila ``email.send`` pendiente para el tick siguiente: su
    antiguedad va aparte y no cuenta como atraso de eventos.
    """
    ahora = datetime.now(timezone.utc)
    store_filter = [] if store_id is None else [WebhookInbox.store_id == store_id]
    outbox_filter = [] if store_id is None else [OutboxMessage.store_id == store_id]

    inbox_pendiente = WebhookInbox.processed_at.is_(None)
    inbox = (
        await db.execute(
            select(
                func.count(WebhookInbox.id),
                func.count(case((WebhookInbox.error.is_not(None), 1))),
                func.min(WebhookInbox.created_at),
            ).where(inbox_pendiente, WebhookInbox.is_active.is_(True), *store_filter)
        )
    ).one()

    es_mail = OutboxMessage.event_type == EVENT_EMAIL_SEND
    outbox = (
        await db.execute(
            select(
                func.count(OutboxMessage.id),
                func.min(case((~es_mail, OutboxMessage.created_at))),
                func.min(case((es_mail, OutboxMessage.created_at))),
            ).where(
                OutboxMessage.processed_at.is_(None),
                OutboxMessage.is_active.is_(True),
                *outbox_filter,
            )
        )
    ).one()
    # Dead letters: agotaron los reintentos (``register_failure`` pone
    # ``processed_at``) y salen de "pendientes"; sin esto no se veian (revision
    # de perf/f4-pay). Cae en ``ix_webhook_inbox_processed_history``. Solo
    # filas activas, como la consulta de pendientes (revision #6).
    dead_letters = await db.scalar(
        select(func.count(WebhookInbox.id)).where(
            WebhookInbox.processed_at >= ahora - timedelta(hours=24),
            WebhookInbox.attempts >= WEBHOOK_INBOX_MAX_ATTEMPTS,
            WebhookInbox.error.is_not(None),
            WebhookInbox.is_active.is_(True),
            *store_filter,
        )
    )
    return {
        "dead_letter_webhooks_24h": int(dead_letters or 0),
        "pending_webhooks": int(inbox[0] or 0),
        "failed_webhooks": int(inbox[1] or 0),
        "pending_outbox": int(outbox[0] or 0),
        "oldest_pending_outbox_seconds": _segundos_desde(ahora, outbox[1]),
        "oldest_pending_inbox_seconds": _segundos_desde(ahora, inbox[2]),
        "oldest_pending_email_send_seconds": _segundos_desde(ahora, outbox[2]),
    }


def _slo_thresholds() -> dict[str, int]:
    return {
        "dead_letter_webhooks_24h": settings.SLO_MAX_DEAD_LETTER_WEBHOOKS_24H,
        "pending_webhooks": settings.SLO_MAX_PENDING_WEBHOOKS,
        "failed_webhooks": settings.SLO_MAX_FAILED_WEBHOOKS,
        "pending_outbox": settings.SLO_MAX_PENDING_OUTBOX,
        "oldest_pending_outbox_seconds": settings.SLO_MAX_OLDEST_PENDING_OUTBOX_SECONDS,
        "oldest_pending_inbox_seconds": settings.SLO_MAX_OLDEST_PENDING_INBOX_SECONDS,
        "oldest_pending_email_send_seconds": (
            settings.SLO_MAX_OLDEST_PENDING_EMAIL_SEND_SECONDS
        ),
    }


# Metrica -> (codigo de alerta, severidad), en el orden en que se reportan.
_SLO_ALERTS = (
    # Un webhook que agoto sus reintentos es un cobro que nadie aplico.
    ("dead_letter_webhooks_24h", "dead_letter_webhooks", "critical"),
    ("pending_webhooks", "pending_webhooks_high", "critical"),
    ("failed_webhooks", "failed_webhooks_high", "critical"),
    ("pending_outbox", "pending_outbox_high", "warning"),
    # F1-25: un cobro acreditado sin aplicar es "pague y sigue pendiente".
    ("oldest_pending_inbox_seconds", "inbox_lag_high", "critical"),
    ("oldest_pending_outbox_seconds", "outbox_lag_high", "warning"),
    ("oldest_pending_email_send_seconds", "email_send_lag_high", "warning"),
)


def _slo_alerts(
    metrics: dict[str, int], thresholds: dict[str, int]
) -> list[dict[str, str | int]]:
    return [
        {
            "code": code,
            "severity": severity,
            "value": metrics[metric],
            "threshold": thresholds[metric],
        }
        for metric, code, severity in _SLO_ALERTS
        if metrics[metric] > thresholds[metric]
    ]


async def _store_public_id(db: AsyncSession, store_id: str) -> str | None:
    """``public_id`` de la tienda: el id que expone el resto de la API.

    AUD2-B5-19: el endpoint devolvia ``user.store_id``, o sea el ULID interno
    de ``stores.id``. Filtrar ids internos es la forma de que empiecen a
    usarse desde afuera; todos los DTOs del repo exponen ``public_id``.
    """
    result = await db.execute(select(Store.public_id).where(Store.id == store_id))
    return result.scalar_one_or_none()


@router.get("/slo")
async def slo_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Estado de webhooks y outbox contra sus umbrales.

    Alcance: el admin de tienda ve la suya; el superadmin ve el consolidado de
    la plataforma. Es la EXCEPCION deliberada a B5-02 ("el superadmin ve su
    propia tienda" en reportes y panel): estas metricas son de
    infraestructura, no del negocio de una tienda. Queda afirmado en
    tests/integration/test_ops_slo.py.
    """
    role = canonical_role(user)
    if role != ROLE_SUPER_ADMIN and not has_any_role(user, STORE_MANAGERS):
        raise PermissionDeniedException("ver SLO")

    # No hace falta mirar is_global_admin aparte: canonical_role ya devuelve
    # ROLE_SUPER_ADMIN cuando el flag esta, asi que el termino extra era
    # inalcanzable y sugeria un "global admin que no es superadmin" que no
    # existe (AUD2-B5-17, mismo patron que reports/router.py). Lo fija
    # test_el_global_admin_siempre_es_rol_superadmin.
    is_global = role == ROLE_SUPER_ADMIN
    # store_scope_for nunca devuelve None: no hay forma de pedir "sin filtro"
    # desde aca, y el alcance global es una decision de este endpoint.
    store_id = store_scope_for(user)
    metrics = await _slo_metrics(db, None if is_global else store_id)
    thresholds = _slo_thresholds()
    alerts = _slo_alerts(metrics, thresholds)

    return {
        "scope": "global" if is_global else "store",
        "store_id": None if is_global else await _store_public_id(db, store_id),
        "status": "ok" if not alerts else "degraded",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "thresholds": thresholds,
        "alerts": alerts,
    }
