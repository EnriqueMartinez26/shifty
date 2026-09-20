from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, status
from fastapi.responses import JSONResponse
from core.router import CanonicalAPIRouter
from sqlalchemy import func, select, text
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
from modules.auth.dependencies import get_current_user
from modules.payments.model import OutboxMessage, WebhookInbox
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
    """``PING`` con el cliente compartido, obtenido DENTRO del try."""
    try:
        async with asyncio.timeout(READINESS_CHECK_TIMEOUT_SECONDS):
            client = await core.redis.get_redis()
            await client.ping()
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


async def _slo_metrics(db: AsyncSession, store_id: str | None) -> dict[str, int]:
    """Webhooks pendientes / fallidos y outbox pendiente; ``None`` = global."""
    store_filter = [] if store_id is None else [WebhookInbox.store_id == store_id]
    outbox_filter = [] if store_id is None else [OutboxMessage.store_id == store_id]

    pending_webhooks_res = await db.execute(
        select(func.count(WebhookInbox.id)).where(
            WebhookInbox.processed_at.is_(None),
            WebhookInbox.is_active.is_(True),
            *store_filter,
        )
    )
    failed_webhooks_res = await db.execute(
        select(func.count(WebhookInbox.id)).where(
            WebhookInbox.processed_at.is_(None),
            WebhookInbox.error.is_not(None),
            WebhookInbox.is_active.is_(True),
            *store_filter,
        )
    )
    pending_outbox_res = await db.execute(
        select(func.count(OutboxMessage.id)).where(
            OutboxMessage.processed_at.is_(None),
            OutboxMessage.is_active.is_(True),
            *outbox_filter,
        )
    )
    return {
        "pending_webhooks": int(pending_webhooks_res.scalar_one() or 0),
        "failed_webhooks": int(failed_webhooks_res.scalar_one() or 0),
        "pending_outbox": int(pending_outbox_res.scalar_one() or 0),
    }


def _slo_thresholds() -> dict[str, int]:
    return {
        "pending_webhooks": settings.SLO_MAX_PENDING_WEBHOOKS,
        "failed_webhooks": settings.SLO_MAX_FAILED_WEBHOOKS,
        "pending_outbox": settings.SLO_MAX_PENDING_OUTBOX,
    }


# Metrica -> (codigo de alerta, severidad), en el orden en que se reportan.
_SLO_ALERTS = (
    ("pending_webhooks", "pending_webhooks_high", "critical"),
    ("failed_webhooks", "failed_webhooks_high", "critical"),
    ("pending_outbox", "pending_outbox_high", "warning"),
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
