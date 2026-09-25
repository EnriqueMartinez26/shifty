"""Dos canjes concurrentes de un cupon con ``max_uses=1``: pasa uno solo.

S-08, 2026-09-18. El router carga cupon y suscripcion antes de
``redeem_coupon`` y los ``SELECT ... FOR UPDATE`` no refrescaban el identity
map (faltaba ``populate_existing``): el segundo canje esperaba el lock, lo
obtenia y validaba ``current_uses`` con el 0 leido antes, asi que los dos
pasaban el tope y el contador quedaba en 1 con dos canjes (regla 4).

Cada canje corre en su propia conexion y los dos cargan las filas ANTES de
que cualquiera tome el lock (una barrera los alinea), que es el orden del
router. Solo en Postgres hay FOR UPDATE real.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import _apply_tenant_context, set_tenant_context
from modules.billing.model import CouponRedemption, Plan, SaaSCoupon, StoreSubscription
from modules.stores.model import Store
from modules.superadmin.repository import SuperAdminRepository
from modules.users.model import User
from tests.postgres.conftest import seed_store_and_admin

pytestmark = pytest.mark.postgres

CODIGO = "PG-ULTIMO-USO"


@asynccontextmanager
async def _como_superadmin(session: AsyncSession) -> AsyncIterator[None]:
    """Contexto de superadmin, como el endpoint (get_current_global_admin)."""
    set_tenant_context(None, True)
    try:
        await _apply_tenant_context(session)
        yield
    finally:
        set_tenant_context(None, False)


async def _sembrar(
    sessions: async_sessionmaker[AsyncSession], slugs: tuple[str, str]
) -> None:
    for slug in slugs:
        await seed_store_and_admin(sessions, slug=slug, email=f"{slug}@demo.com")
    async with sessions() as session:
        async with _como_superadmin(session):
            plan = Plan(name="Plan PG S-08", price=Decimal("10000"), currency="ARS")
            session.add(plan)
            await session.flush()
            tiendas = (
                (await session.execute(select(Store).where(Store.slug.in_(slugs))))
                .scalars()
                .all()
            )
            for tienda in tiendas:
                session.add(
                    StoreSubscription(
                        store_id=tienda.id,
                        plan_id=plan.id,
                        plan_name=plan.name,
                        status="active",
                        base_amount=Decimal("10000"),
                        discount_amount=Decimal("0"),
                        total_amount=Decimal("10000"),
                        currency="ARS",
                        current_period_end=datetime.now(timezone.utc)
                        + timedelta(days=20),
                    )
                )
            session.add(
                SaaSCoupon(
                    code=CODIGO,
                    coupon_type="percent",
                    value=Decimal("10"),
                    max_uses=1,
                    current_uses=0,
                    one_time_per_store=False,
                )
            )
            await session.commit()


async def _canjear(
    sessions: async_sessionmaker[AsyncSession], slug: str, barrera: asyncio.Barrier
) -> str:
    async with sessions() as session:
        async with _como_superadmin(session):
            repo = SuperAdminRepository(session)
            tienda = (
                await session.execute(select(Store).where(Store.slug == slug))
            ).scalar_one()
            actor = (
                await session.execute(
                    select(User).where(User.email == f"{slug}@demo.com")
                )
            ).scalar_one()
            # Como el router: todo queda en el identity map antes del lock.
            suscripcion = await repo.subscriptions.get_store_subscription(tienda.id)
            cupon = await repo.coupons.get_coupon_by_code(CODIGO)
            assert suscripcion is not None and cupon is not None
            await barrera.wait()
            try:
                await repo.coupons.redeem_coupon(tienda, suscripcion, cupon, actor)
            except ValueError as exc:
                await session.rollback()
                return str(exc)
            return "ok"


@pytest.mark.asyncio
async def test_dos_canjes_concurrentes_de_un_cupon_de_un_uso_pasa_uno(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    slugs = ("s08-pg-a", "s08-pg-b")
    await _sembrar(app_sessions, slugs)

    barrera = asyncio.Barrier(2)
    resultados = await asyncio.gather(
        *(_canjear(app_sessions, slug, barrera) for slug in slugs)
    )

    assert sorted(resultados) == sorted(
        ["ok", "El cupón ya alcanzó su límite de usos"]
    ), resultados

    async with app_sessions() as session:
        async with _como_superadmin(session):
            usos = (
                await session.execute(
                    select(SaaSCoupon.current_uses).where(SaaSCoupon.code == CODIGO)
                )
            ).scalar_one()
            canjes = (
                await session.execute(
                    select(func.count()).select_from(CouponRedemption)
                )
            ).scalar_one()
    assert usos == 1
    assert canjes == 1, "el tope max_uses=1 dejo pasar dos canjes"
