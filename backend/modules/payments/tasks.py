from __future__ import annotations

import asyncio

from core.celery_app import celery_app
from core.database import AsyncSessionFactory
from modules.payments.jobs import process_outbox_batch, process_webhook_inbox_batch


@celery_app.task(name="process_payment_outbox", bind=True, max_retries=3)
def process_payment_outbox(self, limit: int = 100) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionFactory() as db:
            return await process_outbox_batch(db, limit=limit)

    try:
        return asyncio.run(_run())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@celery_app.task(name="process_payment_webhook_inbox", bind=True, max_retries=3)
def process_payment_webhook_inbox(self, limit: int = 100) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionFactory() as db:
            return await process_webhook_inbox_batch(db, limit=limit)

    try:
        return asyncio.run(_run())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
