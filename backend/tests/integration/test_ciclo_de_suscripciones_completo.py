"""El ciclo diario de suscripciones no se queda en las primeras 500.

2026-09-20, AUD2-B2-09: ``advance_subscriptions`` seleccionaba
``is_active = True`` ordenado por ``created_at ASC`` con ``limit=500`` y sin
ningun predicado de "le falta trabajo". Con mas de 500 suscripciones activas
cada corrida diaria volvia a mirar las mismas 500 mas viejas (que ya estaban
al dia) y las de mas atras no se avisaban, no pasaban a ``past_due`` y no se
suspendian nunca. Nada lo registraba: ``inspected`` marcaba 500 y parecia
sano. Es plata del negocio: las tiendas nuevas dejaban de pagar sin
consecuencia, y el corte era invisible.

Sintoma reproducido abajo: con ``SUBSCRIPTION_PAGE_SIZE + 5`` suscripciones
activas y la ULTIMA vencida, la corrida no la tocaba.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.billing.model import Plan, StoreSubscription
from modules.billing.service import SUBSCRIPTION_PAGE_SIZE, advance_subscriptions
from modules.billing.subscription_rules import (
    SUBSCRIPTION_GRACE_DAYS,
    SUBSCRIPTION_PAST_DUE,
    SUBSCRIPTION_SUSPENDED,
)
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)

SOBRANTE = 5


async def _tienda(client: AsyncClient, session: AsyncSession, slug: str) -> str:
    public_id, _token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    return (
        await session.execute(select(Store.id).where(Store.public_id == public_id))
    ).scalar_one()


async def _sembrar(
    client: AsyncClient, session: AsyncSession, *, cuantas: int
) -> list[StoreSubscription]:
    """``cuantas`` suscripciones activas, con ``created_at`` creciente.

    El orden importa: la que interesa es la ULTIMA, la que quedaba fuera de
    la pagina. Todas cuelgan de la misma tienda porque el job es
    cross-tenant y no mira el store_id; crear una tienda por fila haria el
    test inviable.
    """
    store_id = await _tienda(client, session, "susc-pagina")
    plan = Plan(name="Plan paginado", price=15000, currency="ARS")
    session.add(plan)
    await session.flush()
    ahora = datetime.now(timezone.utc)
    creadas: list[StoreSubscription] = []
    for i in range(cuantas):
        # Las primeras estan al dia (vencen dentro de un ano); la ultima
        # vencio ayer y necesita pasar a past_due.
        vencida = i == cuantas - 1
        subscription = StoreSubscription(
            store_id=store_id,
            plan_id=plan.id,
            plan_name=plan.name,
            status="active",
            base_amount=plan.price,
            discount_amount=0,
            total_amount=plan.price,
            currency="ARS",
            current_period_start=ahora - timedelta(days=30),
            current_period_end=(
                ahora - timedelta(days=1) if vencida else ahora + timedelta(days=365)
            ),
            # created_at explicito: sin esto todas empatan y "las 500 mas
            # viejas" es un orden arbitrario que no se puede afirmar.
            created_at=ahora - timedelta(seconds=cuantas - i),
        )
        session.add(subscription)
        creadas.append(subscription)
    await session.commit()
    return creadas


@pytest.mark.asyncio
async def test_la_suscripcion_que_no_entra_en_la_primera_pagina_igual_vence(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    creadas = await _sembrar(
        client, test_session, cuantas=SUBSCRIPTION_PAGE_SIZE + SOBRANTE
    )
    ultima = creadas[-1]

    run = await advance_subscriptions(test_session)
    await test_session.commit()

    await test_session.refresh(ultima)
    assert ultima.status == SUBSCRIPTION_PAST_DUE, (
        "la suscripcion vencida quedo fuera de la pagina y nadie la volvio a "
        "mirar: la tienda dejo de pagar sin consecuencia"
    )
    assert run.past_due == 1, run.counters()
    assert run.inspected == SUBSCRIPTION_PAGE_SIZE + SOBRANTE, run.counters()


@pytest.mark.asyncio
async def test_el_recorrido_llega_hasta_la_suspension(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """La segunda etapa del ciclo tambien alcanza a las de atras."""
    creadas = await _sembrar(
        client, test_session, cuantas=SUBSCRIPTION_PAGE_SIZE + SOBRANTE
    )
    ultima = creadas[-1]
    ultima.status = SUBSCRIPTION_PAST_DUE
    ultima.current_period_end = datetime.now(timezone.utc) - timedelta(
        days=SUBSCRIPTION_GRACE_DAYS + 2
    )
    await test_session.commit()

    run = await advance_subscriptions(test_session)
    await test_session.commit()

    await test_session.refresh(ultima)
    assert ultima.status == SUBSCRIPTION_SUSPENDED, run.counters()
    assert run.suspended == 1, run.counters()


@pytest.mark.asyncio
async def test_dos_corridas_seguidas_no_repiten_el_aviso(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Guarda viva: la idempotencia del aviso (``expiry_warning_sent_at``) no
    se pierde al recorrer todas las paginas."""
    creadas = await _sembrar(client, test_session, cuantas=3)
    porvencer = creadas[0]
    porvencer.current_period_end = datetime.now(timezone.utc) + timedelta(days=3)
    await test_session.commit()

    primera = await advance_subscriptions(test_session)
    await test_session.commit()
    segunda = await advance_subscriptions(test_session)
    await test_session.commit()

    assert primera.warned == 1, primera.counters()
    assert segunda.warned == 0, segunda.counters()
