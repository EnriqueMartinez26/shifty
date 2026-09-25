from __future__ import annotations


from celery.app.task import Task
from celery.exceptions import SoftTimeLimitExceeded

from core.celery_app import celery_app
from core.worker_loop import run_in_worker_loop
from core.database import (
    AsyncSessionFactory,
    _apply_tenant_context,
    set_tenant_context,
)
from modules.payments.jobs import (
    MP_BATCH_LIMIT,
    expire_unpaid_appointments,
    process_outbox_tick,
    process_webhook_inbox_batch,
    reconcile_one_payment,
    reconcile_pending_payments,
)


@celery_app.task(name="process_payment_outbox", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def process_payment_outbox(self: Task, limit: int = 100) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionFactory() as db:
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(db)
                # Con el lock del tick: una sola corrida del outbox a la vez.
                return await process_outbox_tick(db, limit=limit)
            finally:
                set_tenant_context(None, False)

    try:
        return run_in_worker_loop(_run())
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))


@celery_app.task(name="process_payment_webhook_inbox", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def process_payment_webhook_inbox(
    self: Task, limit: int = MP_BATCH_LIMIT
) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionFactory() as db:
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(db)
                return await process_webhook_inbox_batch(db, limit=limit)
            finally:
                set_tenant_context(None, False)

    try:
        return run_in_worker_loop(_run())
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))


@celery_app.task(name="reconcile_pending_payments", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def reconcile_pending_payment_holds(
    self: Task, limit: int = MP_BATCH_LIMIT
) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionFactory() as db:
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(db)
                return await reconcile_pending_payments(db, limit=limit)
            finally:
                set_tenant_context(None, False)

    try:
        return run_in_worker_loop(_run())
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))


# Sin reintentos (F1-21): si falla, el poll del cliente la vuelve a pedir a
# los 15 s y la conciliacion general queda como red.
@celery_app.task(name="reconcile_payment_on_demand", bind=True, max_retries=0)  # type: ignore[untyped-decorator]
def reconcile_payment_on_demand(self: Task, payment_id: str) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionFactory() as db:
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(db)
                return await reconcile_one_payment(db, payment_id)
            finally:
                set_tenant_context(None, False)

    return run_in_worker_loop(_run())


@celery_app.task(name="expire_unpaid_appointments", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def expire_unpaid_appointment_holds(self: Task, limit: int = 100) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionFactory() as db:
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(db)
                return await expire_unpaid_appointments(db, limit=limit)
            finally:
                set_tenant_context(None, False)

    try:
        return run_in_worker_loop(_run())
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))
