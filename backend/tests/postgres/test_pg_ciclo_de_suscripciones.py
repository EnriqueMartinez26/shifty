"""El recorrido paginado del ciclo de suscripciones, contra Postgres real.

2026-09-20, AUD2-B2-09: ``advance_subscriptions`` pasa de un tope de 500 a un
cursor por ``(created_at, id)`` que recorre todas las suscripciones activas.
Lo que SQLite no puede probar y aca si: ``FOR UPDATE SKIP LOCKED`` de verdad.
El cursor avanza por la ULTIMA fila DEVUELTA, no por un ``OFFSET``: con otra
corrida sosteniendo filas, un OFFSET se correria justo esa cantidad y dejaria
huecos que nadie vuelve a mirar, que es exactamente el defecto que este id
viene a cerrar.

Dos corridas a la vez sobre el mismo conjunto: entre las dos cada fila se
inspecciona UNA vez (regla 8) y ninguna vencida se queda sin pasar a
``past_due``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import ulid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.database import _apply_tenant_context, set_tenant_context
from modules.billing.model import Plan, StoreSubscription
from modules.billing.service import advance_subscriptions
from modules.billing.subscription_rules import SUBSCRIPTION_PAST_DUE
from tests.postgres.conftest import seed_store_and_admin

pytestmark = pytest.mark.postgres

PAGINA = 5
CUANTAS = PAGINA * 4 + 3
VENCIDAS = 7


async def _sembrar(sessions: async_sessionmaker[AsyncSession], store_id: str) -> None:
    """``CUANTAS`` suscripciones activas; las ultimas ``VENCIDAS`` ya vencieron.

    Las vencidas van al FINAL del orden del cursor a proposito: son las que
    el tope de 500 dejaba fuera para siempre.
    """
    ahora = datetime.now(timezone.utc)
    async with sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            plan = Plan(name="Plan PG paginado", price=15000, currency="ARS")
            session.add(plan)
            await session.flush()
            for i in range(CUANTAS):
                vencida = i >= CUANTAS - VENCIDAS
                session.add(
                    StoreSubscription(
                        id=str(ulid.ULID()),
                        store_id=store_id,
                        plan_id=plan.id,
                        plan_name=plan.name,
                        status="active",
                        base_amount=plan.price,
                        discount_amount=0,
                        total_amount=plan.price,
                        currency="ARS",
                        current_period_start=ahora - timedelta(days=40),
                        current_period_end=(
                            ahora - timedelta(days=1)
                            if vencida
                            else ahora + timedelta(days=365)
                        ),
                        created_at=ahora - timedelta(seconds=CUANTAS - i),
                    )
                )
            await session.commit()
        finally:
            set_tenant_context(None, False)


async def _corrida(sessions: async_sessionmaker[AsyncSession]) -> int:
    """Una corrida completa del ciclo, como la tarea de Celery."""
    async with sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            run = await advance_subscriptions(session, limit=PAGINA)
            await session.commit()
            return run.inspected
        finally:
            set_tenant_context(None, False)


@pytest.mark.asyncio
async def test_dos_corridas_solapadas_recorren_todo_sin_repetir(
    app_sessions: async_sessionmaker[AsyncSession], owner_engine: AsyncEngine
) -> None:
    store_id = await seed_store_and_admin(
        app_sessions, slug="susc-pg", email="susc-pg@example.com"
    )
    await _sembrar(app_sessions, store_id)

    inspeccionadas = await asyncio.gather(
        _corrida(app_sessions), _corrida(app_sessions)
    )

    # Entre las dos corridas, cada fila se miro UNA sola vez: el SKIP LOCKED
    # reparte y el cursor no se saltea lo que la otra tomo.
    assert sum(inspeccionadas) == CUANTAS, inspeccionadas

    async with owner_engine.connect() as conn:
        estados = list(
            (
                await conn.execute(
                    select(
                        StoreSubscription.status, StoreSubscription.created_at
                    ).order_by(StoreSubscription.created_at.asc())
                )
            ).all()
        )
    assert len(estados) == CUANTAS
    vencidas = [fila for fila in estados[-VENCIDAS:]]
    assert all(fila[0] == SUBSCRIPTION_PAST_DUE for fila in vencidas), vencidas
    al_dia = estados[:-VENCIDAS]
    assert all(fila[0] == "active" for fila in al_dia), al_dia
