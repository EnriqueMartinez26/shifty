"""El lock del canje de cupon relee la fila: no valida contra la copia vieja.

Revision V-diff de B3-08, 2026-09-18 (S-08). Sintoma: el router de
``/superadmin/stores/{id}/coupons/redeem`` carga la suscripcion y el cupon en la
sesion ANTES de llamar a ``redeem_coupon``. Los ``SELECT ... FOR UPDATE`` de
``_lock_coupon``/``_lock_subscription`` no llevaban ``populate_existing``, asi
que SQLAlchemy devolvia la instancia del identity map SIN refrescarla con la
fila bloqueada: ``current_uses`` se validaba contra ``max_uses`` y se
incrementaba con el valor leido antes del lock. Dos canjes concurrentes de un
cupon con ``max_uses=1`` pasaban los dos (y el segundo pisaba el contador): la
carrera que el lock tenia que cerrar seguia abierta (regla 4).

Aca "otra transaccion" se modela con un UPDATE de Core con
``synchronize_session=False``: cambia la fila en la base sin tocar el identity
map, que es exactamente lo que ve esta sesion cuando otra commitea antes de su
``FOR UPDATE``. La carrera real entre dos conexiones esta en
``tests/postgres/test_pg_canje_cupon_concurrente.py``.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.billing.model import CouponRedemption, Plan, SaaSCoupon, StoreSubscription
from modules.stores.model import Store
from modules.superadmin.repository import SuperAdminRepository
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)

CODIGO = "ULTIMOUSO"


async def _escenario(
    client: AsyncClient, test_session: AsyncSession, slug: str
) -> tuple[Store, User]:
    await register_and_login(client, slug=slug, email=f"{slug}@test.com")
    tienda = (
        await test_session.execute(select(Store).where(Store.slug == slug))
    ).scalar_one()
    actor = (
        await test_session.execute(select(User).where(User.email == f"{slug}@test.com"))
    ).scalar_one()
    plan = Plan(name=f"Plan {slug}", price=Decimal("10000"), currency="ARS")
    test_session.add(plan)
    await test_session.flush()
    test_session.add_all(
        [
            StoreSubscription(
                store_id=tienda.id,
                plan_id=plan.id,
                plan_name=plan.name,
                status="active",
                base_amount=Decimal("10000"),
                discount_amount=Decimal("0"),
                total_amount=Decimal("10000"),
                currency="ARS",
                current_period_end=datetime.now(timezone.utc) + timedelta(days=20),
            ),
            SaaSCoupon(
                code=CODIGO,
                coupon_type="percent",
                value=Decimal("10"),
                max_uses=1,
                current_uses=0,
                one_time_per_store=False,
            ),
        ]
    )
    await test_session.commit()
    return tienda, actor


@pytest.mark.asyncio
async def test_el_lock_ve_el_ultimo_uso_que_consumio_otra_transaccion(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda, actor = await _escenario(client, test_session, "s08-cupon")
    repo = SuperAdminRepository(test_session)

    # Como el router: suscripcion y cupon quedan en el identity map ANTES del lock.
    suscripcion = await repo.subscriptions.get_store_subscription(tienda.id)
    cupon = await repo.coupons.get_coupon_by_code(CODIGO)
    assert suscripcion is not None and cupon is not None
    assert cupon.current_uses == 0
    cupon_id = cupon.id  # el rollback de abajo expira la instancia

    # Otra transaccion consume el ultimo uso antes de nuestro FOR UPDATE.
    await test_session.execute(
        update(SaaSCoupon)
        .where(SaaSCoupon.id == cupon.id)
        .values(current_uses=1)
        .execution_options(synchronize_session=False)
    )
    await test_session.commit()

    with pytest.raises(ValueError, match="límite de usos"):
        await repo.coupons.redeem_coupon(tienda, suscripcion, cupon, actor)
    await test_session.rollback()

    usos = await test_session.execute(
        select(SaaSCoupon.current_uses).where(SaaSCoupon.id == cupon_id)
    )
    assert usos.scalar_one() == 1, "el canje piso el contador con el valor viejo"
    canjes = await test_session.execute(
        select(func.count()).select_from(CouponRedemption)
    )
    assert canjes.scalar_one() == 0


@pytest.mark.asyncio
async def test_el_lock_ve_la_suscripcion_que_otra_transaccion_suspendio(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda, actor = await _escenario(client, test_session, "s08-suscripcion")
    repo = SuperAdminRepository(test_session)

    suscripcion = await repo.subscriptions.get_store_subscription(tienda.id)
    cupon = await repo.coupons.get_coupon_by_code(CODIGO)
    assert suscripcion is not None and cupon is not None
    assert suscripcion.status == "active"

    await test_session.execute(
        update(StoreSubscription)
        .where(StoreSubscription.id == suscripcion.id)
        .values(status="suspended")
        .execution_options(synchronize_session=False)
    )
    await test_session.commit()

    with pytest.raises(ValueError, match="no está activa"):
        await repo.coupons.redeem_coupon(tienda, suscripcion, cupon, actor)
