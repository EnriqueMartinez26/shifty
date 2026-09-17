"""``GET /superadmin/stores`` resume cada tienda con joins agregados, no con
nueve subconsultas correlacionadas.

Auditoria B3-07, 2026-09-17. Sintoma: ``StoreAdminRepository.list_stores`` tenia
136 lineas (regla 29 de CLAUDE.md) y armaba nueve ``.correlate(Store)
.scalar_subquery()`` que la base evalua **por fila**: con el ``limit=50`` del
router son ~450 subconsultas por request, y las tres de suscripcion repiten el
mismo ``ORDER BY created_at DESC LIMIT 1``.

El riesgo de reescribirlas como joins es el clasico: un join mal escrito
multiplica filas (una tienda repetida por cada usuario o por cada canje) o
pierde la tienda sin suscripcion. Por eso el segundo test arma el peor caso
-- varios usuarios, dos suscripciones y dos canjes en la misma tienda -- y
exige una sola fila por tienda con los contadores exactos.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

import ast
import inspect
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.billing.model import CouponRedemption, Plan, SaaSCoupon, StoreSubscription
from modules.stores.model import Store
from modules.superadmin.repository import StoreAdminRepository
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

JsonDict = dict[str, Any]
PASSWORD = "Password123!"
MAX_LINEAS = 80


async def _token_de_admin_global(
    client: AsyncClient, test_session: AsyncSession, *, slug: str, email: str
) -> str:
    await register_and_login(client, slug=slug, email=email)
    usuario = (
        await test_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    usuario.is_global_admin = True
    await test_session.commit()
    login = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return cast(str, login.json()["access_token"])


def test_list_stores_entra_en_el_tope_de_lineas_de_la_regla_29() -> None:
    source = inspect.getsource(StoreAdminRepository.list_stores)
    cuerpo = ast.parse(source.lstrip()).body[0]
    assert isinstance(cuerpo, ast.AsyncFunctionDef)
    lineas = (cuerpo.end_lineno or 0) - cuerpo.lineno + 1
    assert lineas <= MAX_LINEAS, (
        f"list_stores tiene {lineas} lineas (tope {MAX_LINEAS}, regla 29): "
        "los agregados van en joins, no en subconsultas correlacionadas."
    )


def test_list_stores_no_usa_subconsultas_correlacionadas() -> None:
    source = inspect.getsource(StoreAdminRepository.list_stores)
    assert "correlate(" not in source, (
        "list_stores vuelve a correlacionar subconsultas contra Store: la base "
        "las evalua por fila."
    )


@pytest.mark.asyncio
async def test_el_resumen_de_cada_tienda_no_multiplica_ni_pierde_filas(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token = await _token_de_admin_global(
        client, test_session, slug="sa-listado", email="sa-listado@test.com"
    )
    headers = auth_headers(token)

    tienda = (
        await test_session.execute(select(Store).where(Store.slug == "sa-listado"))
    ).scalar_one()

    # Tres usuarios mas: un admin extra, un empleado activo y uno dado de baja.
    for email, role, activo in (
        ("otro-admin@test.com", UserRole.ADMIN, True),
        ("empleado@test.com", UserRole.STAFF, True),
        ("baja@test.com", UserRole.STAFF, False),
    ):
        test_session.add(
            User(
                email=email,
                hashed_password=hash_password(PASSWORD),
                first_name="Test",
                last_name="User",
                full_name="Test User",
                role=role,
                store_id=tienda.id,
                is_active=activo,
            )
        )

    plan_viejo = Plan(
        name="Plan Viejo",
        price=Decimal("1000"),
        currency="ARS",
        billing_interval="monthly",
    )
    plan_nuevo = Plan(
        name="Plan Nuevo",
        price=Decimal("2000"),
        currency="ARS",
        billing_interval="monthly",
    )
    test_session.add_all([plan_viejo, plan_nuevo])
    await test_session.flush()

    ahora = datetime.now(timezone.utc)
    fin_de_periodo = ahora + timedelta(days=30)
    # Dos suscripciones activas: la fila que se muestra es la mas reciente.
    vieja = StoreSubscription(
        store_id=tienda.id,
        plan_id=plan_viejo.id,
        plan_name=plan_viejo.name,
        status="past_due",
        base_amount=Decimal("1000"),
        total_amount=Decimal("1000"),
        currency="ARS",
        current_period_end=ahora - timedelta(days=1),
        created_at=ahora - timedelta(days=10),
    )
    nueva = StoreSubscription(
        store_id=tienda.id,
        plan_id=plan_nuevo.id,
        plan_name=plan_nuevo.name,
        status="active",
        base_amount=Decimal("2000"),
        total_amount=Decimal("2000"),
        currency="ARS",
        current_period_end=fin_de_periodo,
        created_at=ahora,
    )
    test_session.add_all([vieja, nueva])
    await test_session.flush()

    cupon = SaaSCoupon(
        code="LISTADO10",
        coupon_type="percent",
        value=Decimal("10"),
        one_time_per_store=False,
    )
    test_session.add(cupon)
    await test_session.flush()

    ultimo_canje = ahora - timedelta(days=1)
    for creado in (ahora - timedelta(days=5), ultimo_canje):
        test_session.add(
            CouponRedemption(
                coupon_id=cupon.id,
                store_id=tienda.id,
                subscription_id=nueva.id,
                code_snapshot=cupon.code,
                coupon_type_snapshot=cupon.coupon_type,
                value_snapshot=cupon.value,
                base_amount=Decimal("2000"),
                discount_amount=Decimal("200"),
                final_amount=Decimal("1800"),
                currency="ARS",
                created_at=creado,
            )
        )
    await test_session.commit()

    respuesta = await client.get("/superadmin/stores", headers=headers)
    assert respuesta.status_code == 200, respuesta.text
    filas = cast(list[JsonDict], respuesta.json())

    de_la_tienda = [fila for fila in filas if fila["slug"] == "sa-listado"]
    assert len(de_la_tienda) == 1, (
        f"la tienda aparece {len(de_la_tienda)} veces: el join multiplica filas"
    )
    fila = de_la_tienda[0]
    assert fila["users_count"] == 4
    assert fila["active_users_count"] == 3
    assert fila["admins_count"] == 2
    assert fila["has_subscription"] is True
    assert fila["subscription_status"] == "active"
    assert fila["current_plan_name"] == "Plan Nuevo"
    assert fila["last_redemption_at"] is not None
    assert fila["last_redemption_at"].startswith(ultimo_canje.date().isoformat())


@pytest.mark.asyncio
async def test_una_tienda_sin_suscripcion_ni_canjes_sigue_en_el_listado(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token = await _token_de_admin_global(
        client, test_session, slug="sa-sin-sub", email="sa-sin-sub@test.com"
    )
    headers = auth_headers(token)

    respuesta = await client.get("/superadmin/stores", headers=headers)
    assert respuesta.status_code == 200, respuesta.text
    filas = cast(list[JsonDict], respuesta.json())
    fila = next(item for item in filas if item["slug"] == "sa-sin-sub")
    assert fila["has_subscription"] is False
    assert fila["subscription_status"] is None
    assert fila["current_plan_name"] is None
    assert fila["current_period_end"] is None
    assert fila["last_redemption_at"] is None
    assert fila["users_count"] == 1
    assert fila["admins_count"] == 1

    # El filtro por suscripcion tampoco puede perderla ni duplicarla.
    sin_sub = await client.get(
        "/superadmin/stores?has_subscription=false", headers=headers
    )
    assert sin_sub.status_code == 200, sin_sub.text
    slugs = [item["slug"] for item in cast(list[JsonDict], sin_sub.json())]
    assert slugs.count("sa-sin-sub") == 1
