"""El SuperAdmin no crea admins de tienda en la tienda interna.

2026-10-10, produccion. Sintoma: en ``/superadmin`` "Ver" sobre la tienda
"ejemplo" no daba ninguna senal visible, el usuario creyo que habia fallado y
"Crear admin" dio de alta a un admin de negocio dentro de ``shifty-internal``,
la tienda que solo aloja las cuentas SuperAdmin (``stores.is_internal``,
PR #146). ``POST /superadmin/stores/{id}/admins`` lo aceptaba igual que en
cualquier tienda.

Criterio: ``Store.is_internal``. Una tienda interna rechaza el alta con 409
``INTERNAL_STORE_ADMIN_DENIED`` antes de escribir nada; una tienda comun sigue
igual. El listado y el detalle exponen ``is_internal`` para que el panel
apague el boton antes de que se llegue a enviar.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

PASSWORD = "Password123!"


def _alta(email: str) -> dict[str, Any]:
    return {
        "email": email,
        "password": PASSWORD,
        "first_name": "Barbero",
        "last_name": "Uno",
    }


async def _superadmin_en_tienda_interna(
    client: AsyncClient, session: AsyncSession, slug: str
) -> tuple[str, dict[str, str]]:
    """Como la deja el bootstrap: tienda marcada interna y su SuperAdmin."""
    email = f"{slug}@t.com"
    store, _ = await register_and_login(client, slug=slug, email=email)
    fila = (
        await session.execute(select(Store).where(Store.public_id == store))
    ).scalar_one()
    fila.is_internal = True
    cuenta = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one()
    cuenta.is_global_admin = True
    await session.commit()
    login = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return store, auth_headers(str(login.json()["access_token"]))


async def _cuentas_con_email(session: AsyncSession, email: str) -> int:
    total = await session.execute(
        select(func.count()).select_from(User).where(User.email == email)
    )
    return int(total.scalar_one())


@pytest.mark.asyncio
async def test_no_crea_un_admin_en_la_tienda_interna(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    interna, headers = await _superadmin_en_tienda_interna(
        client, test_session, "interna-alta"
    )

    res = await client.post(
        f"/superadmin/stores/{interna}/admins",
        headers=headers,
        json=_alta("barbero-interna@t.com"),
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "INTERNAL_STORE_ADMIN_DENIED"
    assert await _cuentas_con_email(test_session, "barbero-interna@t.com") == 0


@pytest.mark.asyncio
async def test_en_una_tienda_comun_el_alta_sigue_igual(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Control: la guarda no toca a las tiendas de verdad."""
    _, headers = await _superadmin_en_tienda_interna(
        client, test_session, "interna-control"
    )
    comun, _ = await register_and_login(
        client, slug="ejemplo-comun", email="dueno-ejemplo@t.com"
    )

    res = await client.post(
        f"/superadmin/stores/{comun}/admins",
        headers=headers,
        json=_alta("barbero-comun@t.com"),
    )

    assert res.status_code == 201, res.text
    creado = (
        await test_session.execute(
            select(User).where(User.email == "barbero-comun@t.com")
        )
    ).scalar_one()
    tienda = (
        await test_session.execute(select(Store).where(Store.public_id == comun))
    ).scalar_one()
    assert creado.store_id == tienda.id
    assert creado.role == UserRole.ADMIN
    assert creado.is_global_admin is False


@pytest.mark.asyncio
async def test_el_panel_sabe_cual_es_la_tienda_interna(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Listado y detalle traen ``is_internal``: el panel apaga "Crear admin"."""
    interna, headers = await _superadmin_en_tienda_interna(
        client, test_session, "interna-flag"
    )
    comun, _ = await register_and_login(
        client, slug="comun-flag", email="dueno-flag@t.com"
    )

    lista = await client.get(
        "/superadmin/stores", headers=headers, params={"is_active": "all"}
    )
    assert lista.status_code == 200, lista.text
    por_id = {fila["public_id"]: fila for fila in lista.json()}
    assert por_id[interna]["is_internal"] is True
    assert por_id[comun]["is_internal"] is False

    detalle = await client.get(f"/superadmin/stores/{interna}", headers=headers)
    assert detalle.status_code == 200, detalle.text
    assert detalle.json()["is_internal"] is True
