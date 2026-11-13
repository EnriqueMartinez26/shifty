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
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from core.celery_app import celery_app
from core.database import AsyncSessionFactory, _apply_tenant_context, set_tenant_context
from core.worker_loop import run_in_worker_loop
from modules.billing.service import advance_subscriptions
from modules.notifications.model import NotificationType
from modules.payments.model import OutboxMessage
from modules.stores.model import Store
from modules.users.model import User

logger = structlog.get_logger()
SUBSCRIPTION_ADMIN_NOTICE = "billing.subscription_admin_notice"


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
            if run.admin_notices:
                recipients = list(
                    (
                        await db.execute(
                            select(User.email).where(
                                User.is_active.is_(True),
                                User.is_global_admin.is_(True),
                            )
                        )
                    ).scalars()
                )
                stores = dict(
                    (
                        await db.execute(
                            select(Store.id, Store.name).where(
                                Store.id.in_({notice[0] for notice in run.admin_notices})
                            )
                        )
                    ).all()
                )
                for admin_notice in list(run.admin_notices):
                    store_id, subscription_id, notice, period_end = admin_notice
                    marker_payload = {
                        "subscription_id": subscription_id,
                        "notice": notice,
                        "period_end": period_end,
                    }
                    marker_exists = await db.scalar(
                        select(OutboxMessage.id)
                        .where(
                            OutboxMessage.store_id == store_id,
                            OutboxMessage.event_type == SUBSCRIPTION_ADMIN_NOTICE,
                            OutboxMessage.payload["subscription_id"].as_string()
                            == subscription_id,
                            OutboxMessage.payload["notice"].as_string() == notice,
                            OutboxMessage.payload["period_end"].as_string()
                            == period_end,
                        )
                        .limit(1)
                    )
                    if marker_exists:
                        run.admin_notices.remove(admin_notice)
                        continue
                    db.add(
                        OutboxMessage(
                            store_id=store_id,
                            event_type=SUBSCRIPTION_ADMIN_NOTICE,
                            payload=marker_payload,
                            # Es una llave de deduplicación, no un evento a
                            # despachar en el worker del outbox.
                            processed_at=now,
                        )
                    )
                    store_name = stores.get(store_id, "Una tienda")
                    title = (
                        "Suscripción vencida"
                        if notice == "past_due"
                        else "La página de reservas se suspende en 2 días"
                    )
                    body = (
                        f"{store_name}: el período de la suscripción terminó el "
                        f"{period_end}."
                    )
                    for email in recipients:
                        db.add(
                            OutboxMessage(
                                store_id=store_id,
                                event_type="email.send",
                                payload={
                                    "mail": "store_notification",
                                    "args": {"email": email, "title": title, "body": body},
                                    "source_event": SUBSCRIPTION_ADMIN_NOTICE,
                                    "appointment_id": None,
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
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))


process_subscription_lifecycle = cast(
    Any,
    celery_app.task(name="process_subscription_lifecycle", bind=True, max_retries=3)(
        process_subscription_lifecycle
    ),
)
