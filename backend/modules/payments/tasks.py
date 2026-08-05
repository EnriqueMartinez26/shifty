from __future__ import annotations

import asyncio

from celery.app.task import Task

from core.celery_app import celery_app
from core.database import AsyncSessionFactory
from modules.payments.jobs import (
    expire_unpaid_appointments,
    process_outbox_batch,
    process_webhook_inbox_batch,
    reconcile_pending_payments,
)


@celery_app.task(name="process_payment_outbox", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def process_payment_outbox(self: Task, limit: int = 100) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionFactory() as db:
            return await process_outbox_batch(db, limit=limit)

    try:
        return asyncio.run(_run())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))


@celery_app.task(name="process_payment_webhook_inbox", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def process_payment_webhook_inbox(self: Task, limit: int = 100) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionFactory() as db:
            return await process_webhook_inbox_batch(db, limit=limit)

    try:
        return asyncio.run(_run())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))


@celery_app.task(name="reconcile_pending_payments", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def reconcile_pending_payment_holds(self: Task, limit: int = 100) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionFactory() as db:
            return await reconcile_pending_payments(db, limit=limit)

    try:
        return asyncio.run(_run())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))


@celery_app.task(name="expire_unpaid_appointments", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def expire_unpaid_appointment_holds(self: Task, limit: int = 100) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionFactory() as db:
            return await expire_unpaid_appointments(db, limit=limit)

    try:
        return asyncio.run(_run())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))
