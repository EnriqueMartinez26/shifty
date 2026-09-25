"""B6-10 (2026-09-18): ``GET /services/`` no tenia tope ni paginacion.

Sintoma: el listado del catalogo devolvia todas las filas de la tienda sin
``limit``/``offset``; era el unico listado de panel sin cota (comparar con
``users/router.py``, ``limit`` 1..500 y ``offset`` 0..1_000_000). Un
``?limit=2`` se ignoraba y volvia la lista entera.

Contrato con el front: sin parametros la respuesta sigue siendo una LISTA
(no un objeto paginado) con todos los servicios de una tienda normal, en
orden de alta. El tope por defecto es 500 (el techo del de usuarios): una
tienda con mas de 500 servicios veria la lista cortada sin aviso; se deja
declarado en ``test_tope_por_defecto_es_500``.
"""

from typing import cast

import pytest
import ulid
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.services.model import Service
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


async def _crear_servicio(client: AsyncClient, token: str, nombre: str) -> str:
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": nombre, "duration_minutes": 30, "price": 1500},
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


async def _listar(client: AsyncClient, token: str, query: str = "") -> list[str]:
    res = await client.get(f"/services/{query}", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert isinstance(cuerpo, list)
    return [item["public_id"] for item in cuerpo]


@pytest.mark.asyncio
async def test_limit_y_offset_paginan_sin_cambiar_el_default(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="b6-10-pagina", email="b6-10-pagina@example.com"
    )
    _, token_otra = await register_and_login(
        client, slug="b6-10-otra", email="b6-10-otra@example.com"
    )
    creados = [await _crear_servicio(client, token, f"Servicio {i}") for i in range(3)]
    ajeno = await _crear_servicio(client, token_otra, "Ajeno")

    # Default: la lista completa, en orden de alta (contrato del front).
    assert await _listar(client, token) == creados

    primera = await _listar(client, token, "?limit=2")
    segunda = await _listar(client, token, "?limit=2&offset=2")
    assert primera == creados[:2]
    assert segunda == creados[2:]
    assert ajeno not in primera + segunda
    assert await _listar(client, token, "?offset=3") == []


@pytest.mark.asyncio
async def test_paginacion_convive_con_include_inactive(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="b6-10-inactivos", email="b6-10-inactivos@example.com"
    )
    creados = [await _crear_servicio(client, token, f"Servicio {i}") for i in range(3)]
    res = await client.delete(f"/services/{creados[0]}", headers=auth_headers(token))
    assert res.status_code == 204, res.text

    assert await _listar(client, token, "?limit=1") == [creados[1]]
    assert await _listar(client, token, "?include_inactive=true&limit=1") == [
        creados[0]
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "?limit=0",
        "?limit=501",
        "?limit=-1",
        "?offset=-1",
        "?offset=1000001",
        "?offset=9223372036854775808",
    ],
)
async def test_limit_y_offset_acotados_por_los_dos_lados(
    client: AsyncClient, query: str
) -> None:
    # Regla 9: todo parametro numerico lleva ge Y le; un offset sin techo
    # desbordaba bigint en Postgres (500).
    _, token = await register_and_login(
        client, slug="b6-10-cotas", email="b6-10-cotas@example.com"
    )
    res = await client.get(f"/services/{query}", headers=auth_headers(token))
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_tope_por_defecto_es_500(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="b6-10-tope", email="b6-10-tope@example.com"
    )
    store_id = (
        await test_session.execute(select(Store.id).where(Store.slug == "b6-10-tope"))
    ).scalar_one()
    for i in range(501):
        servicio_id = str(ulid.ULID())
        servicio = Service(
            id=servicio_id,
            public_id=servicio_id,
            store_id=store_id,
            name=f"S{i}",
            duration_minutes=30,
            price=100,
        )
        test_session.add(servicio)
    await test_session.commit()

    assert len(await _listar(client, token)) == 500
    assert len(await _listar(client, token, "?offset=500")) == 1
