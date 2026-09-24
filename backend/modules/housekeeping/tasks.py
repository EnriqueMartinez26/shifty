"""Tarea diaria de retencion (F1-19). La logica vive en ``retention.py``."""

from __future__ import annotations

import structlog
from celery.app.task import Task

from core.celery_app import celery_app
from core.config import settings
from core.database import AsyncSessionFactory, _apply_tenant_context, set_tenant_context
from core.worker_loop import run_in_worker_loop
from modules.housekeeping.retention import purge_expired_data

logger = structlog.get_logger()


# Sin reintentos: cada lote queda commiteado y lo que falte lo toma la corrida
# del dia siguiente.
@celery_app.task(name="purge_expired_data", bind=True, max_retries=0)  # type: ignore[untyped-decorator]
def purge_expired_data_task(self: Task, dry_run: bool | None = None) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionFactory() as db:
            # Mantenimiento global: sin request, necesita el bypass para
            # alcanzar las filas de TODAS las tiendas (shifty_app es NOBYPASSRLS).
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(db)
                return await purge_expired_data(db, dry_run=dry_run)
            finally:
                set_tenant_context(None, False)

    resultado = run_in_worker_loop(_run())
    logger.info(
        "purge_expired_data_done",
        dry_run=settings.RETENTION_DRY_RUN if dry_run is None else dry_run,
        **resultado,
    )
    return resultado
