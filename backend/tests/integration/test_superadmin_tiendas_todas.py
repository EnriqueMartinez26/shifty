"""Superadmin: "Todas" las tiendas y el total del listado.

2026-09-24. Sintoma (revision-funcional-front.md, FF-24): la pestana "Todas"
del superadmin mostraba solo las activas (``is_active`` vale ``True`` por
defecto y no habia forma de pedir "sin filtro") y cortaba en 50 sin saber
cuantas habia.

Contrato (aditivo): ``is_active=all`` ademas de ``true``/``false`` (sin el
parametro, solo activas: igual que antes). La respuesta sigue siendo la
lista; el total de filas que cumplen los filtros viaja en el header
``X-Total-Count`` (cambiar la lista por un objeto no seria aditivo).
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from main import origins
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.integration.test_superadmin_listado_de_tiendas import (
    _token_de_admin_global,
)


async def _tres_tiendas(client: AsyncClient, test_session: AsyncSession) -> str:
    token = await _token_de_admin_global(
        client, test_session, slug="sa-todas-1", email="sa-todas@test.com"
    )
    await register_and_login(client, slug="sa-todas-2", email="sa-todas-2@test.com")
    await register_and_login(client, slug="sa-todas-3", email="sa-todas-3@test.com")
    await test_session.execute(
        update(Store).where(Store.slug == "sa-todas-3").values(is_active=False)
    )
    await test_session.commit()
    return token


def _slugs(res: Any) -> list[str]:
    return sorted(item["slug"] for item in cast(list[dict[str, Any]], res.json()))


@pytest.mark.asyncio
async def test_is_active_all_trae_activas_e_inactivas_con_el_total(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers = auth_headers(await _tres_tiendas(client, test_session))

    por_defecto = await client.get("/superadmin/stores", headers=headers)
    activas = await client.get("/superadmin/stores?is_active=true", headers=headers)
    inactivas = await client.get("/superadmin/stores?is_active=false", headers=headers)
    todas = await client.get("/superadmin/stores?is_active=all", headers=headers)

    assert _slugs(por_defecto) == _slugs(activas) == ["sa-todas-1", "sa-todas-2"]
    assert _slugs(inactivas) == ["sa-todas-3"]
    assert _slugs(todas) == ["sa-todas-1", "sa-todas-2", "sa-todas-3"]
    assert por_defecto.headers["x-total-count"] == "2"
    assert inactivas.headers["x-total-count"] == "1"
    assert todas.headers["x-total-count"] == "3"


@pytest.mark.asyncio
async def test_el_total_no_depende_de_la_pagina(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers = auth_headers(await _tres_tiendas(client, test_session))

    pagina = await client.get(
        "/superadmin/stores?is_active=all&limit=1&offset=1", headers=headers
    )
    busqueda = await client.get(
        "/superadmin/stores?is_active=all&search=todas-2", headers=headers
    )

    assert len(pagina.json()) == 1
    assert pagina.headers["x-total-count"] == "3"
    assert _slugs(busqueda) == ["sa-todas-2"]
    assert busqueda.headers["x-total-count"] == "1"


@pytest.mark.asyncio
async def test_valores_invalidos_422(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers = auth_headers(await _tres_tiendas(client, test_session))

    for query in ("is_active=todas", "limit=201", "limit=0", "offset=1000001"):
        res = await client.get(f"/superadmin/stores?{query}", headers=headers)
        assert res.status_code == 422, (query, res.text)


@pytest.mark.asyncio
async def test_el_navegador_puede_leer_el_total(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers = auth_headers(await _tres_tiendas(client, test_session))

    res = await client.get(
        "/superadmin/stores", headers={**headers, "Origin": origins[0]}
    )

    expuestos = res.headers["access-control-expose-headers"].lower()
    assert "x-total-count" in expuestos
