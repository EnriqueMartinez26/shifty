"""Tarea diaria del ciclo de vida de la suscripcion.

Avisa N dias antes del vencimiento, pasa ``active`` a ``past_due`` al vencer
y ``past_due`` a ``suspended`` al agotar la gracia. El aviso viaja por el
outbox (notificacion in-app + mail a los administradores), como el resto de
los avisos al dueno: aca no se manda ningun mail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

import structlog

from core.celery_app import celery_app
from core.database import AsyncSessionFactory, _apply_tenant_context, set_tenant_context
from core.worker_loop import run_in_worker_loop
from modules.billing.service import advance_subscriptions
from modules.notifications.model import NotificationType
from modules.payments.model import OutboxMessage

logger = structlog.get_logger()


async def run_subscription_lifecycle(*, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    async with AsyncSessionFactory() as db:
        # Job global cross-tenant: sin request necesita el bypass para ver las
        # suscripciones de TODAS las tiendas (shifty_app es NOBYPASSRLS).
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(db)
            run = await advance_subscriptions(db, now=now)
            for store_id, days_left, plan_name in run.warnings:
                db.add(
                    OutboxMessage(
                        store_id=store_id,
                        event_type=NotificationType.SUBSCRIPTION_EXPIRING.value,
                        payload={
                            "days_left": days_left,
                            "plan_name": plan_name,
                        },
                    )
                )
            await db.commit()
        finally:
            set_tenant_context(None, False)
    logger.info("subscription_lifecycle_processed", **run.counters())
    return run.counters()


def process_subscription_lifecycle(self: Any) -> dict[str, int]:
    try:
        return run_in_worker_loop(run_subscription_lifecycle())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))


process_subscription_lifecycle = cast(
    Any,
    celery_app.task(name="process_subscription_lifecycle", bind=True, max_retries=3)(
        process_subscription_lifecycle
    ),
)
