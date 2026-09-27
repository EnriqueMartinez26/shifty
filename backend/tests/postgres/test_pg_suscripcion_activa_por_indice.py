"""F1-17 (plan de rendimiento, R7-09 / R4-05): la suscripcion activa usa su indice.

2026-09-24. ``get_active_subscription`` corre en cada escritura del panel (la
guarda de tienda suspendida). Filtraba ``is_active IS true``: el indice parcial
``uq_store_subscriptions_active_store`` es ``WHERE is_active = true`` y Postgres
no prueba que ``IS true`` implique ``= true``, asi que leia todas las
suscripciones de la tienda (historial de renovaciones incluido). Con
``is_active = true`` el plan va directo a la unica fila activa.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.database import _apply_tenant_context, set_tenant_context
from modules.billing.service import get_active_subscription
from tests.postgres.conftest import seed_store_and_admin
from tests.postgres.planes import (
    condiciones_de_indice,
    plan_de,
    resumen,
    sentencias_capturadas,
)

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_la_suscripcion_activa_sale_del_indice_parcial(
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
) -> None:
    store = await seed_store_and_admin(
        app_sessions, slug="pg-suscripcion", email="pg-suscripcion@demo.com"
    )
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "insert into plans (id, name, price, created_at, updated_at) "
                "values ('PLAN-PG', 'Plan', 100, now(), now())"
            )
        )
        # Historial de renovaciones: muchas inactivas, una activa.
        await conn.execute(
            text(
                "insert into store_subscriptions (id, store_id, plan_id, status, "
                "base_amount, total_amount, is_active, created_at, updated_at) "
                "select 'SUB' || lpad(g::text, 20, '0'), :store, 'PLAN-PG', "
                "case when g = 1 then 'active' else 'cancelled' end, 100, 100, g = 1, "
                "now() - g * interval '30 days', now() "
                "from generate_series(1, 3000) g"
            ),
            {"store": store},
        )
        await conn.execute(text("analyze store_subscriptions"))

    with sentencias_capturadas(app_engine) as capturadas:
        async with app_sessions() as session:
            set_tenant_context(store, False)
            try:
                await _apply_tenant_context(session)
                activa = await get_active_subscription(session, store)
            finally:
                set_tenant_context(None, False)
    assert activa is not None and activa.id == "SUB" + "1".rjust(20, "0")

    sentencia = next(s for s in capturadas if "FROM store_subscriptions" in s[0])
    plan = await plan_de(app_engine, sentencia, store_id=store)
    assert "uq_store_subscriptions_active_store" in condiciones_de_indice(plan), (
        f"{sentencia[0]}\n{resumen(plan)}"
    )
