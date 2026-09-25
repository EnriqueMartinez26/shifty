"""F1-14 (plan de rendimiento, R3-01 / R3-02 / R7-05 / R7-08): indices parciales.

2026-09-24. Tres consultas que corren todo el tiempo recorrian historico:

- ``_expired_holds_query`` (job de vencimiento, cada minuto) caia en el indice
  plano ``ix_appointments_expires_at``; ``expires_at`` nunca se limpia, asi que
  barria todas las retenciones viejas ya confirmadas o vencidas.
  ``ix_appointments_hold_expiry`` solo tiene las retenciones vivas.
- El reclamo de ``payment.preference.expire`` con lease vencido (cada minuto)
  caia en ``ix_outbox_messages_event_type``: todo el historico del evento.
  ``ix_outbox_expire_claims`` solo tiene los reclamados.
- El contador de no leidas (cada 60 s por usuario del panel) recorria todas
  las notificaciones de la tienda. ``ix_notifications_store_unread`` solo
  tiene las no leidas y reemplaza a ``ix_notifications_store_id`` y
  ``ix_notifications_read_at``.

Se siembra historico, se corre ``ANALYZE`` y se explica la sentencia REAL de
cada camino como ``shifty_app``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.database import _apply_tenant_context, set_tenant_context
from modules.notifications.repository import NotificationRepository
from modules.payments.jobs import _claim_and_expire_preferences, _expired_holds_query
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import register_and_login
from tests.postgres.planes import (
    condiciones_de_indice,
    plan_de,
    resumen,
    sentencias_capturadas,
)

pytestmark = pytest.mark.postgres


async def _sembrar(
    owner_engine: AsyncEngine, store: str, service: str, staff: str
) -> None:
    async with owner_engine.begin() as conn:
        service_id = (
            await conn.execute(
                text("select id from services where public_id = :p"), {"p": service}
            )
        ).scalar_one()
        # Retenciones viejas: expires_at quedo puesto en turnos ya resueltos.
        await conn.execute(
            text(
                "insert into appointments (id, store_id, staff_id, service_id, "
                "client_name, starts_at, duration_minutes, status, expires_at, "
                "version, created_at, updated_at) "
                "select 'HOLD' || lpad(g::text, 20, '0'), :store, :staff, :service, "
                "'Historia', date_trunc('hour', now()) - g * interval '8 hours', 30, "
                "case when g % 2 = 0 then 'completed' else 'expired' end, "
                "now() - g * interval '8 hours', 1, now(), now() "
                "from generate_series(1, 4000) g"
            ),
            {"store": store, "staff": staff, "service": service_id},
        )
        # Historico del outbox: vencimientos de link ya procesados, y un reclamo
        # vivo (lease sin vencer: la corrida no lo retoma ni llama a MP).
        await conn.execute(
            text(
                "insert into outbox_messages (id, store_id, event_type, payload, "
                "processed_at, error, attempts, is_active, created_at, updated_at) "
                "select 'OUT' || lpad(g::text, 20, '0'), :store, "
                "'payment.preference.expire', '{}'::json, now() - g * interval '1 hour', "
                "null, 1, true, now(), now() "
                "from generate_series(1, 4000) g"
            ),
            {"store": store},
        )
        await conn.execute(
            text(
                "insert into outbox_messages (id, store_id, event_type, payload, "
                "processed_at, error, attempts, is_active, created_at, updated_at) "
                "values ('OUTCLAIM', :store, 'payment.preference.expire', '{}'::json, "
                "now(), 'claimed:payment.preference.expire', 0, "
                "true, now(), now())"
            ),
            {"store": store},
        )
        # Notificaciones: casi todas leidas.
        await conn.execute(
            text(
                "insert into notifications (id, store_id, type, title, read_at, "
                "is_active, created_at, updated_at) "
                "select 'NOTI' || lpad(g::text, 20, '0'), :store, 'payment.approved', "
                "'Historia', case when g % 400 = 0 then null else now() end, true, "
                "now() - g * interval '1 hour', now() "
                "from generate_series(1, 4000) g"
            ),
            {"store": store},
        )
        for tabla in ("appointments", "outbox_messages", "notifications"):
            await conn.execute(text(f"analyze {tabla}"))


@pytest.mark.asyncio
async def test_las_consultas_de_historico_usan_su_indice_parcial(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
) -> None:
    store, token = await register_and_login(
        client, app_sessions, slug="pg-parciales", email="pg-parciales@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-parciales@demo.com")
    await add_staff_schedule(
        client, token, staff, target_date=datetime.now(timezone.utc)
    )
    await _sembrar(owner_engine, store, service, staff)

    with sentencias_capturadas(app_engine) as capturadas:
        async with app_sessions() as session:
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(session)
                await session.execute(
                    _expired_holds_query(datetime.now(timezone.utc), 100)
                )
                await session.rollback()
                await _claim_and_expire_preferences(session, store_id=store)
            finally:
                set_tenant_context(None, False)
        async with app_sessions() as session:
            set_tenant_context(store, False)
            try:
                await _apply_tenant_context(session)
                await NotificationRepository(session).count_unread(store)
            finally:
                set_tenant_context(None, False)

    def una(filtro: str) -> tuple[str, object]:
        encontradas = [s for s in capturadas if filtro in s[0]]
        assert encontradas, [sql for sql, _ in capturadas]
        return encontradas[0]

    esperados = [
        (una("appointments.expires_at <="), "ix_appointments_hold_expiry", True),
        (una("outbox_messages.processed_at <"), "ix_outbox_expire_claims", True),
        (una("FROM notifications"), "ix_notifications_store_unread", False),
    ]
    for sentencia, indice, bypass in esperados:
        plan = await plan_de(
            app_engine,
            sentencia,
            store_id="" if bypass else store,
            global_admin=bypass,
        )
        assert indice in condiciones_de_indice(plan), f"{sentencia[0]}\n{resumen(plan)}"


@pytest.mark.asyncio
async def test_los_indices_de_notificaciones_reemplazados_ya_no_existen(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.connect() as conn:
        nombres = {
            fila[0]
            for fila in (
                await conn.execute(
                    text(
                        "select indexname from pg_indexes where tablename = 'notifications'"
                    )
                )
            ).all()
        }
    assert "ix_notifications_store_unread" in nombres
    assert not {"ix_notifications_store_id", "ix_notifications_read_at"} & nombres
