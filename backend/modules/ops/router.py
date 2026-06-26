from __future__ import annotations

from collections.abc import Awaitable
from datetime import datetime, timezone
from typing import Any, cast

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
    errors: list[str] = []

    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover
        db_ok = False
        errors.append(f"db:{type(exc).__name__}")

    try:
        await cast(Awaitable[bool], redis.ping())
    except Exception as exc:  # pragma: no cover
        redis_ok = False
        errors.append(f"redis:{type(exc).__name__}")

    return {
        "status": "ok" if db_ok and redis_ok else "degraded",
        "time": now,
        "components": {"db": db_ok, "redis": redis_ok},
        "errors": errors,
    }


@router.get("/slo")
async def slo_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    role = canonical_role(user)
    if role != ROLE_SUPER_ADMIN and not has_any_role(user, STORE_MANAGERS):
        raise PermissionDeniedException("ver SLO")

    is_global = role == ROLE_SUPER_ADMIN or bool(user.is_global_admin)
    store_filter = [] if is_global else [WebhookInbox.store_id == user.store_id]
    outbox_filter = [] if is_global else [OutboxMessage.store_id == user.store_id]

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

    pending_webhooks = int(pending_webhooks_res.scalar_one() or 0)
    failed_webhooks = int(failed_webhooks_res.scalar_one() or 0)
    pending_outbox = int(pending_outbox_res.scalar_one() or 0)

    alerts: list[dict[str, str | int]] = []
    if pending_webhooks > settings.SLO_MAX_PENDING_WEBHOOKS:
        alerts.append(
            {
                "code": "pending_webhooks_high",
                "severity": "critical",
                "value": pending_webhooks,
                "threshold": settings.SLO_MAX_PENDING_WEBHOOKS,
            }
        )
    if failed_webhooks > settings.SLO_MAX_FAILED_WEBHOOKS:
        alerts.append(
            {
                "code": "failed_webhooks_high",
                "severity": "critical",
                "value": failed_webhooks,
                "threshold": settings.SLO_MAX_FAILED_WEBHOOKS,
            }
        )
    if pending_outbox > settings.SLO_MAX_PENDING_OUTBOX:
        alerts.append(
            {
                "code": "pending_outbox_high",
                "severity": "warning",
                "value": pending_outbox,
                "threshold": settings.SLO_MAX_PENDING_OUTBOX,
            }
        )

    return {
        "scope": "global" if is_global else "store",
        "store_id": None if is_global else user.store_id,
        "status": "ok" if not alerts else "degraded",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "pending_webhooks": pending_webhooks,
            "failed_webhooks": failed_webhooks,
            "pending_outbox": pending_outbox,
        },
        "thresholds": {
            "pending_webhooks": settings.SLO_MAX_PENDING_WEBHOOKS,
            "failed_webhooks": settings.SLO_MAX_FAILED_WEBHOOKS,
            "pending_outbox": settings.SLO_MAX_PENDING_OUTBOX,
        },
        "alerts": alerts,
    }
