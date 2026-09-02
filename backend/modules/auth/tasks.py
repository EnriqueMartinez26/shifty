from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from celery.app.task import Task
from sqlalchemy import delete, or_

from core.celery_app import celery_app
from core.database import AsyncSessionFactory, _apply_tenant_context, set_tenant_context
from modules.auth.session_model import AuthSession

# Cuanto tiempo se conservan las sesiones muertas antes de borrarlas. Se dejan
# unos dias por forense (de que IP/UA vino un acceso sospechoso) y despues se
# purgan: es una tabla de credenciales, no un archivo historico.
_RETENTION_DAYS = 30


@celery_app.task(name="purge_expired_auth_sessions", bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def purge_expired_auth_sessions(
    self: Task, retention_days: int = _RETENTION_DAYS
) -> int:
    async def _run() -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        async with AsyncSessionFactory() as db:
            # Tarea de mantenimiento global: corre fuera de un request, sin
            # tenant. Necesita el bypass para alcanzar todas las tiendas.
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(db)
                result = await db.execute(
                    delete(AuthSession).where(
                        or_(
                            AuthSession.expires_at < cutoff,
                            AuthSession.revoked_at < cutoff,
                        )
                    )
                )
                await db.commit()
                deleted = getattr(result, "rowcount", 0) or 0
                return int(deleted)
            finally:
                set_tenant_context(None, False)

    return asyncio.run(_run())
