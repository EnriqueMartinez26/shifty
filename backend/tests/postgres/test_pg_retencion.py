"""Retencion (F1-19) contra Postgres real: RLS, DELETE por lotes y advisory lock.

SQLite no prueba tres cosas de la purga diaria:

- que con el rol de la app (RLS forzada, sin BYPASSRLS) el bypass de la
  tarea alcance las filas de todas las tiendas;
- que el ``DELETE ... WHERE id IN (SELECT ... LIMIT n)`` por lotes borre lo
  vencido y nada mas (pendientes, reclamos en curso, no leidas, auditoria);
- que una segunda corrida con el advisory lock tomado no haga nada.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.database import _apply_tenant_context, set_tenant_context
from modules.audit.model import AuditLog
from modules.housekeeping.retention import RETENTION_JOB_LOCK, purge_expired_data
from modules.notifications.model import Notification
from modules.otp.model import OtpVerification
from modules.payments.jobs import JOB_LOCK_NAMESPACE, PREFERENCE_EXPIRE_CLAIM
from modules.payments.model import OutboxMessage, WebhookInbox
from tests.postgres.conftest import seed_store_and_admin
from tests.postgres.test_pg_lotes_skip_locked import _con_bypass

pytestmark = pytest.mark.postgres

AHORA = datetime.now(timezone.utc)


def _hace(dias: float) -> datetime:
    return AHORA - timedelta(days=dias)


async def _sembrar(sessions: async_sessionmaker[AsyncSession]) -> None:
    tienda = await seed_store_and_admin(
        sessions, slug="pg-retencion", email="pg-retencion@test.com"
    )
    async with sessions() as db:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(db)
            db.add_all(
                [
                    OutboxMessage(
                        store_id=tienda,
                        event_type="x",
                        payload={},
                        created_at=_hace(100),
                        processed_at=_hace(95),
                    ),
                    OutboxMessage(
                        store_id=tienda,
                        event_type="x",
                        payload={},
                        created_at=_hace(200),
                    ),
                    OutboxMessage(
                        store_id=tienda,
                        event_type="x",
                        payload={},
                        created_at=_hace(200),
                        processed_at=_hace(100),
                        error=PREFERENCE_EXPIRE_CLAIM,
                    ),
                    WebhookInbox(
                        store_id=tienda,
                        event_id="pg-ret-viejo",
                        payload={},
                        created_at=_hace(100),
                        processed_at=_hace(95),
                    ),
                    WebhookInbox(
                        store_id=tienda,
                        event_id="pg-ret-pendiente",
                        payload={},
                        created_at=_hace(200),
                    ),
                    OtpVerification(
                        store_id=tienda,
                        phone="+5491100000000",
                        code_hash="h1",
                        expires_at=_hace(8),
                    ),
                    OtpVerification(
                        store_id=tienda,
                        phone="+5491100000000",
                        code_hash="h2",
                        expires_at=_hace(3),
                    ),
                    Notification(
                        store_id=tienda,
                        type="x",
                        title="t",
                        created_at=_hace(300),
                        read_at=_hace(200),
                    ),
                    Notification(
                        store_id=tienda, type="x", title="t", created_at=_hace(300)
                    ),
                    AuditLog(
                        store_id=tienda,
                        created_at=_hace(4000),
                        resource_type="Appointment",
                        resource_id="x",
                        action="update",
                    ),
                ]
            )
            await db.commit()
        finally:
            set_tenant_context(None, False)


async def _filas(owner_engine: AsyncEngine) -> dict[str, int]:
    tablas = (
        "outbox_messages",
        "webhook_inbox",
        "otp_verifications",
        "notifications",
        "audit_logs",
    )
    async with owner_engine.connect() as conn:
        return {
            tabla: int(
                (await conn.execute(text(f"select count(*) from {tabla}"))).scalar_one()
            )
            for tabla in tablas
        }


@pytest.mark.asyncio
async def test_la_purga_borra_lo_vencido_con_el_rol_de_la_app(
    app_sessions: async_sessionmaker[AsyncSession], owner_engine: AsyncEngine
) -> None:
    await _sembrar(app_sessions)

    resultado = await _con_bypass(
        app_sessions, lambda db: purge_expired_data(db, now=AHORA)
    )

    assert resultado == {
        "outbox_messages": 1,
        "webhook_inbox": 1,
        "otp_verifications": 1,
        "notifications": 1,
    }
    assert await _filas(owner_engine) == {
        "outbox_messages": 2,
        "webhook_inbox": 1,
        "otp_verifications": 1,
        "notifications": 1,
        "audit_logs": 1,
    }


@pytest.mark.asyncio
async def test_con_el_lock_tomado_la_segunda_corrida_no_borra_nada(
    app_sessions: async_sessionmaker[AsyncSession], owner_engine: AsyncEngine
) -> None:
    await _sembrar(app_sessions)
    antes = await _filas(owner_engine)

    async with owner_engine.connect() as conn:
        await conn.execute(
            text("select pg_advisory_lock(:ns, hashtext(:clave))"),
            {"ns": JOB_LOCK_NAMESPACE, "clave": RETENTION_JOB_LOCK},
        )
        try:
            resultado = await _con_bypass(
                app_sessions, lambda db: purge_expired_data(db, now=AHORA)
            )
        finally:
            await conn.execute(
                text("select pg_advisory_unlock(:ns, hashtext(:clave))"),
                {"ns": JOB_LOCK_NAMESPACE, "clave": RETENTION_JOB_LOCK},
            )

    assert set(resultado.values()) == {0}
    assert await _filas(owner_engine) == antes
