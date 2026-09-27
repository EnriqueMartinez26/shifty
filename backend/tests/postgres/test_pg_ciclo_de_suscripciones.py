"""El recorrido paginado del ciclo de suscripciones, contra Postgres real.

2026-09-20, AUD2-B2-09: ``advance_subscriptions`` pasa de un tope de 500 a un
cursor por ``(created_at, id)`` que recorre todas las suscripciones activas.
Lo que SQLite no puede probar y aca si: ``FOR UPDATE SKIP LOCKED`` de verdad.
El cursor avanza por la ULTIMA fila DEVUELTA, no por un ``OFFSET``: con otra
corrida sosteniendo filas, un OFFSET se correria justo esa cantidad y dejaria
huecos que nadie vuelve a mirar, que es exactamente el defecto que este id
viene a cerrar.

Dos corridas a la vez sobre el mismo conjunto: entre las dos cada fila se
inspecciona UNA vez (regla 8), ninguna vencida se queda sin pasar a
``past_due`` y ninguna "por vencer" recibe el aviso dos veces.

2026-09-23, AUD2-POST-01: el indice parcial ``uq_store_subscriptions_active_store``
admite UNA suscripcion activa por tienda, asi que la siembra crea una tienda
por suscripcion (el job es cross-tenant y no mira el ``store_id``).
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
from modules.billing.service import DailyRun, advance_subscriptions
from modules.billing.subscription_rules import SUBSCRIPTION_PAST_DUE
from modules.stores.model import Store

pytestmark = pytest.mark.postgres

PAGINA = 5
CUANTAS = PAGINA * 4 + 3
VENCIDAS = 7
POR_VENCER = 4
AL_DIA = CUANTAS - VENCIDAS - POR_VENCER


def _vencimiento(i: int, ahora: datetime) -> datetime:
    """Al dia primero, despues las "por vencer" y al FINAL las vencidas.

    Las vencidas van ultimas en el orden del cursor a proposito: son las que
    el tope de 500 dejaba fuera para siempre.
    """
    if i >= CUANTAS - VENCIDAS:
        return ahora - timedelta(days=1)
    if i >= AL_DIA:
        return ahora + timedelta(days=3)
    return ahora + timedelta(days=365)


async def _sembrar(sessions: async_sessionmaker[AsyncSession]) -> None:
    """``CUANTAS`` suscripciones activas, cada una en su propia tienda."""
    ahora = datetime.now(timezone.utc)
    async with sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            plan = Plan(name="Plan PG paginado", price=15000, currency="ARS")
            session.add(plan)
            await session.flush()
            store_ids = [str(ulid.ULID()) for _ in range(CUANTAS)]
            for i, store_id in enumerate(store_ids):
                session.add(
                    Store(
                        id=store_id,
                        public_id=store_id,
                        name=f"Tienda susc-pg-{i:02d}",
                        slug=f"susc-pg-{i:02d}",
                        theme_config={"business_type": "general"},
                    )
                )
            # Without a relationship() between the two models the unit of work
            # does not guarantee stores are inserted first; flush them explicitly.
            await session.flush()
            for i, store_id in enumerate(store_ids):
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
                        current_period_end=_vencimiento(i, ahora),
                        created_at=ahora - timedelta(seconds=CUANTAS - i),
                    )
                )
            await session.commit()
        finally:
            set_tenant_context(None, False)


async def _corrida(sessions: async_sessionmaker[AsyncSession]) -> DailyRun:
    """Una corrida completa del ciclo, como la tarea de Celery."""
    async with sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            run = await advance_subscriptions(session, limit=PAGINA)
            await session.commit()
            return run
        finally:
            set_tenant_context(None, False)


async def _estado_final(
    owner_engine: AsyncEngine,
) -> list[tuple[str, datetime | None]]:
    """``(status, expiry_warning_sent_at)`` en el orden del cursor."""
    async with owner_engine.connect() as conn:
        filas = (
            await conn.execute(
                select(
                    StoreSubscription.status,
                    StoreSubscription.expiry_warning_sent_at,
                ).order_by(
                    StoreSubscription.created_at.asc(), StoreSubscription.id.asc()
                )
            )
        ).all()
    return [(str(fila[0]), fila[1]) for fila in filas]


@pytest.mark.asyncio
async def test_dos_corridas_solapadas_recorren_todo_sin_repetir(
    app_sessions: async_sessionmaker[AsyncSession], owner_engine: AsyncEngine
) -> None:
    await _sembrar(app_sessions)

    corridas = await asyncio.gather(_corrida(app_sessions), _corrida(app_sessions))

    # Entre las dos corridas, cada fila se miro UNA sola vez: el SKIP LOCKED
    # reparte y el cursor no se saltea lo que la otra tomo.
    inspeccionadas = [run.inspected for run in corridas]
    assert sum(inspeccionadas) == CUANTAS, inspeccionadas
    # ...y cada "por vencer" recibio UN aviso, no uno por corrida.
    avisadas = [run.warned for run in corridas]
    assert sum(avisadas) == POR_VENCER, avisadas

    estados = await _estado_final(owner_engine)
    assert len(estados) == CUANTAS
    al_dia = estados[:AL_DIA]
    assert all(fila == ("active", None) for fila in al_dia), al_dia
    por_vencer = estados[AL_DIA : AL_DIA + POR_VENCER]
    assert all(fila[0] == "active" and fila[1] is not None for fila in por_vencer), (
        por_vencer
    )
    vencidas = estados[-VENCIDAS:]
    assert all(fila[0] == SUBSCRIPTION_PAST_DUE for fila in vencidas), vencidas

    # Una tercera corrida, ya sin solapamiento, no vuelve a avisar ni toca
    # la marca: ``expiry_warning_sent_at`` se escribe una sola vez.
    tercera = await _corrida(app_sessions)
    assert tercera.warned == 0, tercera.counters()
    assert await _estado_final(owner_engine) == estados
