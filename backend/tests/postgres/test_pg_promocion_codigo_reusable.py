"""El codigo de una promocion dada de baja se reusa, contra Postgres real (B2-14).

La suite de SQLite crea el esquema desde los modelos; aca el esquema sale de
la cadena de migraciones, asi que esto prueba que ``f8c0e2a4b6d8`` dejo el
indice unico PARCIAL (``WHERE is_active``) y no la restriccion vieja sobre
(store_id, code), que devolvia 409 para siempre al recrear un codigo borrado.
"""

from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres


async def _crear(client: AsyncClient, token: str, code: str) -> "tuple[int, str]":
    res = await client.post(
        "/promotions/",
        headers=auth_headers(token),
        json={"code": code, "title": "Verano", "value": 10},
    )
    return res.status_code, cast(str, res.json().get("public_id", ""))


@pytest.mark.asyncio
async def test_el_indice_de_codigo_es_parcial_sobre_las_activas(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.connect() as conn:
        definicion = (
            await conn.execute(
                text(
                    "select indexdef from pg_indexes "
                    "where indexname = 'uq_store_promotions_active_code'"
                )
            )
        ).scalar_one()
        vieja = (
            await conn.execute(
                text(
                    "select count(*) from pg_constraint "
                    "where conname = 'uq_store_promotions_store_code'"
                )
            )
        ).scalar_one()
    assert "UNIQUE" in definicion and "WHERE is_active" in definicion, definicion
    assert vieja == 0


@pytest.mark.asyncio
async def test_borrar_y_recrear_el_mismo_codigo(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    _store, token = await register_and_login(
        client, app_sessions, slug="pg-promo-reuso", email="pg-promo-reuso@demo.com"
    )
    codigo, vieja = await _crear(client, token, "VERANO20")
    assert codigo == 201
    borrar = await client.delete(f"/promotions/{vieja}", headers=auth_headers(token))
    assert borrar.status_code == 204, borrar.text

    codigo, nueva = await _crear(client, token, "VERANO20")
    assert codigo == 201
    assert nueva != vieja

    # Y entre activas la unicidad sigue en pie.
    codigo, _ = await _crear(client, token, "VERANO20")
    assert codigo == 409
