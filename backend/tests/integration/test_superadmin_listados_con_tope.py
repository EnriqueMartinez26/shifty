"""Los listados de usuarios del superadmin tienen techo y cuentan en SQL.

AUD2-B3-03, 2026-09-20. Sintoma: ``UserAdminRepository.list_store_users`` no
aceptaba ``limit`` ni ``offset`` y devolvia la tabla entera de la tienda. La
usaban ``GET /superadmin/stores/{id}/users`` y ``get_store_overview`` (con
``include_inactive=True``), que ademas serializaba la lista completa y sacaba
``admins_count``/``users_count``/``active_users_count`` de un ``len(...)`` en
Python. La tabla ``users`` crece con CADA reserva publica (el portal crea un
``User`` con rol ``client`` por cliente nuevo), asi que la pantalla de detalle
de tienda --la que se abre para decidir una suspension-- devolvia decenas de
miles de objetos con email y telefono en una sola respuesta. Reglas 9 y 11.
``/coupon-redemptions`` tampoco llevaba limite.
"""

from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.superadmin.repository import STORE_OVERVIEW_USERS_LIMIT
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

PASSWORD = "Password123!"


async def _tienda_con_superadmin(
    client: AsyncClient, test_session: AsyncSession, *, slug: str, email: str
) -> tuple[str, str]:
    store_public_id, _ = await register_and_login(client, slug=slug, email=email)
    usuario = (
        await test_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    usuario.is_global_admin = True
    await test_session.commit()
    login = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return store_public_id, cast(str, login.json()["access_token"])


async def _sembrar_clientes(
    test_session: AsyncSession, *, email_dueno: str, cantidad: int, inactivos: int
) -> int:
    """Crea ``cantidad`` clientes en la tienda del dueno y devuelve el total."""
    dueno = (
        await test_session.execute(select(User).where(User.email == email_dueno))
    ).scalar_one()
    clave = hash_password(PASSWORD)
    for indice in range(cantidad):
        test_session.add(
            User(
                email=f"cliente-{indice}-{email_dueno}",
                hashed_password=clave,
                first_name="Cliente",
                last_name=str(indice),
                full_name=f"Cliente {indice}",
                role=UserRole.CLIENT,
                store_id=dueno.store_id,
                is_active=indice >= inactivos,
            )
        )
    await test_session.commit()
    total = (
        await test_session.execute(select(User).where(User.store_id == dueno.store_id))
    ).scalars()
    return len(list(total))


@pytest.mark.asyncio
async def test_el_overview_no_serializa_la_tabla_entera_y_cuenta_en_sql(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    email = "sa-overview@test.com"
    store_public_id, token = await _tienda_con_superadmin(
        client, test_session, slug="sa-overview", email=email
    )
    total = await _sembrar_clientes(
        test_session,
        email_dueno=email,
        cantidad=STORE_OVERVIEW_USERS_LIMIT + 2,
        inactivos=3,
    )

    res = await client.get(
        f"/superadmin/stores/{store_public_id}/overview", headers=auth_headers(token)
    )
    assert res.status_code == 200, res.text
    usuarios = res.json()["users"]

    assert len(usuarios["users"]) <= STORE_OVERVIEW_USERS_LIMIT, (
        "el overview sigue serializando la tabla entera de la tienda"
    )
    # Los contadores salen de SQL, no de len(...) de la lista truncada.
    assert usuarios["users_count"] == total
    assert usuarios["active_users_count"] == total - 3
    # El dueno es el unico admin y aparece completo aunque la lista se trunque.
    assert usuarios["admins_count"] == 1
    assert len(usuarios["admins"]) == 1


@pytest.mark.asyncio
async def test_el_listado_de_usuarios_de_una_tienda_pagina(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    email = "sa-users@test.com"
    store_public_id, token = await _tienda_con_superadmin(
        client, test_session, slug="sa-users", email=email
    )
    await _sembrar_clientes(test_session, email_dueno=email, cantidad=6, inactivos=0)
    headers = auth_headers(token)
    ruta = f"/superadmin/stores/{store_public_id}/users"

    primera = await client.get(f"{ruta}?limit=3&offset=0", headers=headers)
    assert primera.status_code == 200, primera.text
    assert len(primera.json()) == 3

    segunda = await client.get(f"{ruta}?limit=3&offset=3", headers=headers)
    assert segunda.status_code == 200, segunda.text
    ids_primera = {fila["public_id"] for fila in primera.json()}
    ids_segunda = {fila["public_id"] for fila in segunda.json()}
    assert not (ids_primera & ids_segunda), "la segunda pagina repite la primera"

    # Regla 9: ge Y le en los dos parametros.
    for consulta in ("?limit=0", "?limit=201", "?offset=-1", "?offset=1000001"):
        fuera = await client.get(f"{ruta}{consulta}", headers=headers)
        assert fuera.status_code == 422, f"{consulta}: {fuera.text}"


@pytest.mark.asyncio
async def test_los_canjes_de_una_tienda_llevan_limite(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store_public_id, token = await _tienda_con_superadmin(
        client, test_session, slug="sa-canjes", email="sa-canjes@test.com"
    )
    headers = auth_headers(token)
    ruta = f"/superadmin/stores/{store_public_id}/coupon-redemptions"

    normal = await client.get(f"{ruta}?limit=10", headers=headers)
    assert normal.status_code == 200, normal.text

    for consulta in ("?limit=0", "?limit=201"):
        fuera = await client.get(f"{ruta}{consulta}", headers=headers)
        assert fuera.status_code == 422, f"{consulta}: {fuera.text}"
