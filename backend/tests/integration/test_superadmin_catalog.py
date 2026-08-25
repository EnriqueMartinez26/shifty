"""Panel de superadministracion: alta de tiendas, planes y cupones.

Es el modulo con el que se aprovisionan los clientes del SaaS. Si se rompe, no
se pueden dar de alta tiendas nuevas, y era el que menos cobertura tenia.
"""

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


async def _global_admin(
    client: AsyncClient, test_session: AsyncSession, *, slug: str, email: str
) -> str:
    """Registra una tienda y promueve a su admin a administrador global."""
    _, _token = await register_and_login(client, slug=slug, email=email)
    usuario = (
        await test_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    usuario.is_global_admin = True
    await test_session.commit()

    relogin = await client.post(
        "/auth/login", json={"email": email, "password": "Password123!"}
    )
    assert relogin.status_code == 200, relogin.text
    return cast(str, relogin.json()["access_token"])


@pytest.mark.asyncio
async def test_solo_un_admin_global_entra_al_panel(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token_comun = await register_and_login(
        client, slug="sa-no-global", email="sa-no-global@test.com"
    )
    negado = await client.get("/superadmin/stores", headers=auth_headers(token_comun))
    assert negado.status_code in {401, 403}, negado.text

    token = await _global_admin(
        client, test_session, slug="sa-si-global", email="sa-si-global@test.com"
    )
    permitido = await client.get("/superadmin/stores", headers=auth_headers(token))
    assert permitido.status_code == 200, permitido.text


@pytest.mark.asyncio
async def test_alta_de_tienda_y_su_administrador(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El flujo real de aprovisionamiento de un cliente nuevo."""
    token = await _global_admin(
        client, test_session, slug="sa-alta", email="sa-alta@test.com"
    )

    tienda = await client.post(
        "/superadmin/stores",
        headers=auth_headers(token),
        json={"name": "Barberia Nueva", "slug": "barberia-nueva"},
    )
    assert tienda.status_code == 201, tienda.text
    store_public_id = cast(str, tienda.json()["public_id"])

    admin = await client.post(
        f"/superadmin/stores/{store_public_id}/admins",
        headers=auth_headers(token),
        json={
            "email": "duenio@barberia-nueva.com",
            "password": "Password123!",
            "first_name": "Duenio",
            "last_name": "Nuevo",
        },
    )
    assert admin.status_code == 201, admin.text

    usuarios = await client.get(
        f"/superadmin/stores/{store_public_id}/users", headers=auth_headers(token)
    )
    assert usuarios.status_code == 200, usuarios.text
    assert any(u["email"] == "duenio@barberia-nueva.com" for u in usuarios.json())

    detalle = await client.get(
        f"/superadmin/stores/{store_public_id}", headers=auth_headers(token)
    )
    assert detalle.status_code == 200, detalle.text

    overview = await client.get(
        f"/superadmin/stores/{store_public_id}/overview", headers=auth_headers(token)
    )
    assert overview.status_code == 200, overview.text


@pytest.mark.asyncio
async def test_editar_una_tienda_desde_el_panel(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token = await _global_admin(
        client, test_session, slug="sa-editar", email="sa-editar@test.com"
    )
    creada = await client.post(
        "/superadmin/stores",
        headers=auth_headers(token),
        json={"name": "Para Editar", "slug": "para-editar"},
    )
    store_public_id = cast(str, creada.json()["public_id"])

    editada = await client.patch(
        f"/superadmin/stores/{store_public_id}",
        headers=auth_headers(token),
        json={"name": "Nombre Cambiado", "cancellation_hours": 48},
    )
    assert editada.status_code == 200, editada.text
    assert editada.json()["name"] == "Nombre Cambiado"


@pytest.mark.asyncio
async def test_ciclo_de_vida_de_un_plan(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token = await _global_admin(
        client, test_session, slug="sa-planes", email="sa-planes@test.com"
    )

    creado = await client.post(
        "/superadmin/plans",
        headers=auth_headers(token),
        json={
            "name": "Plan Basico",
            "description": "Hasta 3 profesionales",
            "price": 15000,
            "currency": "ARS",
            "billing_interval": "monthly",
            "max_staff": 3,
        },
    )
    assert creado.status_code == 201, creado.text
    plan_id = cast(str, creado.json()["public_id"])

    listado = await client.get("/superadmin/plans", headers=auth_headers(token))
    assert listado.status_code == 200
    assert any(p["public_id"] == plan_id for p in listado.json())

    editado = await client.patch(
        f"/superadmin/plans/{plan_id}",
        headers=auth_headers(token),
        json={"price": 18000, "max_staff": 5},
    )
    assert editado.status_code == 200, editado.text
    assert float(editado.json()["price"]) == 18000.0


@pytest.mark.asyncio
async def test_un_plan_con_precio_negativo_se_rechaza(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token = await _global_admin(
        client, test_session, slug="sa-plan-malo", email="sa-plan-malo@test.com"
    )
    res = await client.post(
        "/superadmin/plans",
        headers=auth_headers(token),
        json={"name": "Plan Invalido", "price": -100},
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_ciclo_de_vida_de_un_cupon(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token = await _global_admin(
        client, test_session, slug="sa-cupones", email="sa-cupones@test.com"
    )
    ahora = datetime.now(timezone.utc)

    creado = await client.post(
        "/superadmin/coupons",
        headers=auth_headers(token),
        json={
            "code": "BIENVENIDA20",
            "coupon_type": "percent",
            "value": 20,
            "max_uses": 10,
            "valid_from": ahora.isoformat(),
            "valid_until": (ahora + timedelta(days=30)).isoformat(),
            "description": "Veinte por ciento el primer mes",
        },
    )
    assert creado.status_code == 201, creado.text
    coupon_id = cast(str, creado.json()["public_id"])

    listado = await client.get("/superadmin/coupons", headers=auth_headers(token))
    assert listado.status_code == 200
    assert any(c["public_id"] == coupon_id for c in listado.json())

    detalle = await client.get(
        f"/superadmin/coupons/{coupon_id}", headers=auth_headers(token)
    )
    assert detalle.status_code == 200, detalle.text

    editado = await client.patch(
        f"/superadmin/coupons/{coupon_id}",
        headers=auth_headers(token),
        json={"max_uses": 50},
    )
    assert editado.status_code == 200, editado.text
    assert editado.json()["max_uses"] == 50


@pytest.mark.asyncio
async def test_un_cupon_sin_valor_positivo_se_rechaza(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token = await _global_admin(
        client, test_session, slug="sa-cupon-malo", email="sa-cupon-malo@test.com"
    )
    res = await client.post(
        "/superadmin/coupons",
        headers=auth_headers(token),
        json={"code": "GRATIS", "coupon_type": "percent", "value": 0},
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_promover_y_revocar_un_administrador_global(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token = await _global_admin(
        client, test_session, slug="sa-promueve", email="sa-promueve@test.com"
    )
    await register_and_login(client, slug="sa-promovido", email="promovido@test.com")
    objetivo = (
        await test_session.execute(
            select(User).where(User.email == "promovido@test.com")
        )
    ).scalar_one()

    promovido = await client.patch(
        f"/superadmin/users/{objetivo.public_id}/global-admin",
        headers=auth_headers(token),
        json={"is_global_admin": True},
    )
    assert promovido.status_code == 200, promovido.text
    assert promovido.json()["is_global_admin"] is True

    revocado = await client.patch(
        f"/superadmin/users/{objetivo.public_id}/global-admin",
        headers=auth_headers(token),
        json={"is_global_admin": False},
    )
    assert revocado.status_code == 200, revocado.text
    assert revocado.json()["is_global_admin"] is False
