"""``store_terms_acceptances`` bajo RLS real y por la API (L1, 2026-09-25).

La tabla es de una tienda: con el rol de la app y sin ``WHERE store_id``,
cada contexto ve solo sus aceptaciones. El alta por la API escribe bajo el
contexto de la tienda del admin (la politica ``WITH CHECK`` lo exige).
"""

from __future__ import annotations

from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres


async def _contar(app_engine: AsyncEngine, store_id: str | None) -> int:
    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text(
                    "select set_config('app.current_store_id', :sid, true), "
                    "set_config('app.is_global_admin', 'false', true)"
                ),
                {"sid": store_id or "0"},
            )
            total = (
                await conn.execute(text("select count(*) from store_terms_acceptances"))
            ).scalar_one()
            return cast(int, total)


async def _store_id(owner_engine: AsyncEngine, public_id: str) -> str:
    async with owner_engine.connect() as conn:
        fila = (
            await conn.execute(
                text("select id from stores where public_id = :p or id = :p"),
                {"p": public_id},
            )
        ).scalar_one()
        return str(fila)


@pytest.mark.asyncio
async def test_cada_tienda_ve_solo_sus_aceptaciones(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
) -> None:
    tienda_a, token_a = await register_and_login(
        client, app_sessions, slug="pg-b2b-a", email="pg-b2b-a@demo.com"
    )
    tienda_b, token_b = await register_and_login(
        client, app_sessions, slug="pg-b2b-b", email="pg-b2b-b@demo.com"
    )
    for token in (token_a, token_a, token_b):
        res = await client.post(
            "/stores/me/terms-acceptance", headers=auth_headers(token)
        )
        assert res.status_code == 201, res.text

    id_a = await _store_id(owner_engine, tienda_a)
    id_b = await _store_id(owner_engine, tienda_b)
    assert await _contar(app_engine, id_a) == 2
    assert await _contar(app_engine, id_b) == 1
    assert await _contar(app_engine, None) == 0

    estado = await client.get(
        "/stores/me/terms-acceptance", headers=auth_headers(token_b)
    )
    assert estado.status_code == 200, estado.text
    assert estado.json()["current_version_accepted"] is True
