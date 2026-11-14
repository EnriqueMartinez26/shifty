"""Tarea periodica: ofertas de lista de espera vencidas pasan a la siguiente."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from core.celery_app import celery_app
from core.database import AsyncSessionFactory, _apply_tenant_context, set_tenant_context
from core.worker_loop import run_in_worker_loop
from modules.payments.model import OutboxMessage
from modules.waitlist.offers import PendingOfferEmail, expire_lapsed_offers


def persist_pending_offer_emails(
    db: AsyncSession, pendientes: list[PendingOfferEmail]
) -> None:
    """Guarda las reofertas en el outbox, en la misma transaccion del estado."""
    # Import local: payments.jobs consume waitlist.offers y su dispatcher es el
    # encargado de reclamar email.send fuera de la transaccion.
    from modules.payments.jobs import EVENT_EMAIL_SEND

    for pendiente in pendientes:
        db.add(
            OutboxMessage(
                store_id=pendiente.store_id,
                event_type=EVENT_EMAIL_SEND,
                payload={
                    "mail": "waitlist_offer",
                    "args": {
                        "email": pendiente.email,
                        "details": pendiente.details,
                    },
                    "source_event": "waitlist.offer.reoffered",
                },
            )
        )


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
            persist_pending_offer_emails(db, resultado.pending_emails)
            await db.commit()
        finally:
            set_tenant_context(None, False)
    # El dispatcher normal reclama y manda las filas fuera de esta transaccion.
    # Si la captura SMTP cae antes de DATA, conserva la fila para el proximo tick.
    return resultado.counters()


def process_waitlist_offers(self: Any) -> dict[str, int]:
    try:
        return run_in_worker_loop(process_waitlist_offers_once())
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))


process_waitlist_offers = cast(
    Any,
    celery_app.task(name="process_waitlist_offers", bind=True, max_retries=3)(
        process_waitlist_offers
    ),
)
