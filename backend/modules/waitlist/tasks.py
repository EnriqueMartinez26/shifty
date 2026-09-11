"""Tarea periodica: ofertas de lista de espera vencidas pasan a la siguiente."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from core.celery_app import celery_app
from core.database import AsyncSessionFactory, _apply_tenant_context, set_tenant_context
from core.worker_loop import run_in_worker_loop
from modules.notifications.tasks import enqueue_waitlist_offer_email
from modules.waitlist.offers import expire_lapsed_offers


async def process_waitlist_offers_once(
    *, now: datetime | None = None
) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    async with AsyncSessionFactory() as db:
        # Job global cross-tenant: bypass RLS para ver todas las tiendas.
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(db)
            resultado = await expire_lapsed_offers(db, now=now)
            await db.commit()
        finally:
            set_tenant_context(None, False)
    # Los mails salen con la transaccion ya cerrada (regla 5).
    for pendiente in resultado.pending_emails:
        await enqueue_waitlist_offer_email(
            email=pendiente.email, details=pendiente.details
        )
    return resultado.counters()


def process_waitlist_offers(self: Any) -> dict[str, int]:
    try:
        return run_in_worker_loop(process_waitlist_offers_once())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))


process_waitlist_offers = cast(
    Any,
    celery_app.task(name="process_waitlist_offers", bind=True, max_retries=3)(
        process_waitlist_offers
    ),
)
