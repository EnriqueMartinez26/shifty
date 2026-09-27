"""Los PATCH del superadmin respetan el ``null`` explicito.

Auditoria B3-19, 2026-09-16 (decision del 2026-09-18). Sintoma: el router
distingue "no vino" de "vino null" (``model_dump(exclude_unset=True)``) pero
los cuatro ``update_*`` del repositorio de superadmin hacian
``if value is not None: setattr(...)``: ``PATCH {"logo_url": null}`` respondia
200 sin cambiar nada. El PATCH mentia y el panel no podia borrar un logo, la
descripcion de un plan o el vencimiento de un cupon.

Ahora un ``null`` explicito borra el valor en una columna que admite NULL; en
una columna NOT NULL (nombre, precio, valor del cupon) se ignora como antes, en
lugar de convertirse en un 409 o un 500. Lo que no vino no se toca.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

JsonDict = dict[str, Any]


async def _superadmin(
    client: AsyncClient, test_session: AsyncSession, slug: str
) -> tuple[str, dict[str, str]]:
    store_public_id, token = await register_and_login(
        client, slug=slug, email=f"{slug}@test.com"
    )
    usuario = (
        await test_session.execute(select(User).where(User.email == f"{slug}@test.com"))
    ).scalar_one()
    usuario.is_global_admin = True
    await test_session.commit()
    return store_public_id, auth_headers(token)


async def _patch(
    client: AsyncClient, headers: dict[str, str], ruta: str, cuerpo: JsonDict
) -> JsonDict:
    res = await client.patch(ruta, headers=headers, json=cuerpo)
    assert res.status_code == 200, res.text
    return cast(JsonDict, res.json())


@pytest.mark.asyncio
async def test_el_logo_de_una_tienda_se_puede_borrar(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda, headers = await _superadmin(client, test_session, "null-tienda")
    ruta = f"/superadmin/stores/{tienda}"

    con_logo = await _patch(
        client, headers, ruta, {"logo_url": "https://cdn.example.com/logo.png"}
    )
    assert con_logo["logo_url"] == "https://cdn.example.com/logo.png"

    # Un campo que no vino no borra el logo.
    otro = await _patch(client, headers, ruta, {"primary_color": "#112233"})
    assert otro["logo_url"] == "https://cdn.example.com/logo.png"

    borrado = await _patch(client, headers, ruta, {"logo_url": None})
    assert borrado["logo_url"] is None, "el null explicito no borro el logo"

    # null en una columna NOT NULL se ignora: ni 409 ni 500.
    igual = await _patch(client, headers, ruta, {"name": None})
    assert igual["name"] == con_logo["name"]


@pytest.mark.asyncio
async def test_la_descripcion_y_el_tope_de_un_plan_se_pueden_borrar(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, headers = await _superadmin(client, test_session, "null-plan")
    alta = await client.post(
        "/superadmin/plans",
        headers=headers,
        json={
            "name": "Plan Null",
            "description": "Con descripcion",
            "price": "1000",
            "currency": "ARS",
            "billing_interval": "monthly",
            "max_staff": 5,
        },
    )
    assert alta.status_code == 201, alta.text
    ruta = f"/superadmin/plans/{alta.json()['public_id']}"

    plan = await _patch(
        client, headers, ruta, {"description": None, "max_staff": None, "price": None}
    )
    assert plan["description"] is None
    assert plan["max_staff"] is None
    assert plan["price"] == alta.json()["price"], "price es NOT NULL: se ignora"


@pytest.mark.asyncio
async def test_el_vencimiento_y_el_tope_de_un_cupon_se_pueden_borrar(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, headers = await _superadmin(client, test_session, "null-cupon")
    alta = await client.post(
        "/superadmin/coupons",
        headers=headers,
        json={
            "code": "NULLCUPON",
            "coupon_type": "percent",
            "value": "10",
            "max_uses": 5,
            "valid_until": "2030-01-01T00:00:00+00:00",
            "description": "Promo",
        },
    )
    assert alta.status_code == 201, alta.text
    ruta = f"/superadmin/coupons/{alta.json()['public_id']}"

    cupon = await _patch(
        client,
        headers,
        ruta,
        {"valid_until": None, "max_uses": None, "description": None},
    )
    assert cupon["valid_until"] is None
    assert cupon["max_uses"] is None
    assert cupon["description"] is None

    # value es NOT NULL: un null se ignora (antes: None > 100 -> 500).
    igual = await _patch(client, headers, ruta, {"value": None})
    assert igual["value"] == alta.json()["value"]


@pytest.mark.asyncio
async def test_el_telefono_de_un_usuario_se_puede_borrar(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, headers = await _superadmin(client, test_session, "null-usuario")
    _, _ = await register_and_login(
        client, slug="null-usuario-b", email="null-usuario-b@test.com"
    )
    usuario = (
        await test_session.execute(
            select(User).where(User.email == "null-usuario-b@test.com")
        )
    ).scalar_one()
    usuario.phone = "1144445555"
    await test_session.commit()
    ruta = f"/superadmin/users/{usuario.public_id}"

    borrado = await _patch(client, headers, ruta, {"phone": None})
    assert borrado["phone"] is None
