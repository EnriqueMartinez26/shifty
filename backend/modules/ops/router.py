from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Depends
from core.router import CanonicalAPIRouter
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import PermissionDeniedException

from core.config import settings
from core.database import get_db
from core.redis import get_redis
from core.roles import ROLE_SUPER_ADMIN, STORE_MANAGERS, canonical_role, has_any_role
from modules.auth.dependencies import get_current_user
from modules.payments.model import OutboxMessage, WebhookInbox
from modules.users.model import User

router = CanonicalAPIRouter(prefix="/ops", tags=["Operations"])


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    if not settings.OPS_ENABLE_PUBLIC_HEALTH:
        return {"status": "disabled"}
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@router.get("/health/ready")
async def readiness(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    db_ok = True
    redis_ok = True

    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover
        db_ok = False

    try:
        await redis.ping()
    except Exception:  # pragma: no cover
        redis_ok = False

    status_value = "ok" if db_ok and redis_ok else "degraded"

    # Con el flag apagado se devuelve SOLO el estado agregado: ni el detalle de
    # componentes ni -antes- el nombre de clase de la excepcion (info util para
    # un atacante anonimo que sondea la infra). El nombre de clase se elimino en
    # ambos casos.
    if not settings.OPS_ENABLE_PUBLIC_HEALTH:
        return {"status": status_value, "time": now}

    return {
        "status": status_value,
        "time": now,
        "components": {"db": db_ok, "redis": redis_ok},
    }


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


@router.get("/slo")
async def slo_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    role = canonical_role(user)
    if role != ROLE_SUPER_ADMIN and not has_any_role(user, STORE_MANAGERS):
        raise PermissionDeniedException("ver SLO")

    is_global = role == ROLE_SUPER_ADMIN or bool(user.is_global_admin)
    metrics = await _slo_metrics(db, None if is_global else user.store_id)
    thresholds = _slo_thresholds()
    alerts = _slo_alerts(metrics, thresholds)

    return {
        "scope": "global" if is_global else "store",
        "store_id": None if is_global else user.store_id,
        "status": "ok" if not alerts else "degraded",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "thresholds": thresholds,
        "alerts": alerts,
    }
