"""La purga de retencion usa indices parciales, no barre la tabla (F1-19).

Revision de perf/f2b (2026-09-24): ``outbox_messages``, ``webhook_inbox`` y
``notifications`` no tenian indice sobre la columna que filtra la purga (solo
parciales de pendientes/no leidas), asi que cada lote de 5.000 recorria la
tabla entera. La migracion ``e5f7a9b1c3d6`` agrega
``ix_outbox_processed_history``, ``ix_webhook_inbox_processed_history`` y
``ix_notifications_read_history``. Se captura el DELETE real de la purga y se
explica como ``shifty_app`` con el bypass de la tarea.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.database import _apply_tenant_context, set_tenant_context
from modules.housekeeping.retention import purge_expired_data
from tests.postgres.conftest import seed_store_and_admin
from tests.postgres.planes import condiciones_de_indice, plan_de, resumen
from tests.postgres.planes import sentencias_capturadas

pytestmark = pytest.mark.postgres


async def _historico(owner_engine: AsyncEngine, store: str) -> None:
    async with owner_engine.begin() as conn:
        for tabla in ("outbox_messages", "webhook_inbox"):
            extra = ", event_type" if tabla == "outbox_messages" else ", event_id"
            valor = ", 'x'" if tabla == "outbox_messages" else ", 'EV' || g"
            await conn.execute(
                text(
                    f"insert into {tabla} (id, store_id, payload, processed_at, "
                    f"error, attempts, is_active, created_at, updated_at{extra}) "
                    f"select '{tabla[:3]}' || lpad(g::text, 20, '0'), :store, "
                    "'{}'::json, now() - g * interval '30 minutes', null, 0, true, "
                    f"now(), now(){valor} from generate_series(1, 4000) g"
                ),
                {"store": store},
            )
        await conn.execute(
            text(
                "insert into notifications (id, store_id, type, title, read_at, "
                "is_active, created_at, updated_at) "
                "select 'NOT' || lpad(g::text, 20, '0'), :store, 'x', 't', "
                "now() - g * interval '30 minutes', true, now(), now() "
                "from generate_series(1, 4000) g"
            ),
            {"store": store},
        )
        for tabla in ("outbox_messages", "webhook_inbox", "notifications"):
            await conn.execute(text(f"analyze {tabla}"))


@pytest.mark.asyncio
async def test_cada_lote_de_la_purga_usa_su_indice_parcial(
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
) -> None:
    store = await seed_store_and_admin(
        app_sessions, slug="pg-ret-idx", email="pg-ret-idx@test.com"
    )
    await _historico(owner_engine, store)

    with sentencias_capturadas(app_engine) as capturadas:
        async with app_sessions() as session:
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(session)
                await purge_expired_data(
                    session, now=datetime.now(timezone.utc), dry_run=True
                )
            finally:
                set_tenant_context(None, False)

    def conteo(tabla: str) -> tuple[str, object]:
        encontradas = [
            s for s in capturadas if f"FROM {tabla}" in s[0] and "count(" in s[0]
        ]
        assert encontradas, [sql for sql, _ in capturadas]
        return encontradas[0]

    esperados = {
        "outbox_messages": "ix_outbox_processed_history",
        "webhook_inbox": "ix_webhook_inbox_processed_history",
        "notifications": "ix_notifications_read_history",
    }
    for tabla, indice in esperados.items():
        plan = await plan_de(app_engine, conteo(tabla), global_admin=True)
        assert indice in condiciones_de_indice(plan), f"{tabla}\n{resumen(plan)}"
