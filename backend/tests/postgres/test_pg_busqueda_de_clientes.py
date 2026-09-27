"""FF-20 / F4-03: la busqueda de clientes queda acotada a la tienda.

2026-09-24. ``GET /users/?q=`` busca por nombre con ``ILIKE`` y por digitos
del telefono con ``LIKE``. Ninguno de los dos es leakproof: bajo RLS nunca
son condicion de indice (CLAUDE.md §3). Lo que se exige es que el plan quede
acotado por la tienda: ``users.store_id = $1`` como ``Index Cond`` (igualdad
leakproof) y el ``ILIKE`` como filtro sobre las filas de esa tienda, sin
``Seq Scan`` de ``users``. Se explica la sentencia REAL que manda la app, como
``shifty_app`` y con el contexto de la tienda.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.postgres.conftest import auth_headers, register_and_login
from tests.postgres.planes import (
    condiciones_de_indice,
    escaneos_secuenciales,
    plan_de,
    resumen,
    sentencias_capturadas,
)

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["ana", "11 5555"])
async def test_la_busqueda_de_clientes_usa_el_indice_de_la_tienda(
    q: str,
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
) -> None:
    store, token = await register_and_login(
        client, app_sessions, slug="busca-plan", email="busca-plan@demo.com"
    )
    async with owner_engine.begin() as conn:
        store_id = (
            await conn.execute(
                text("select id from stores where public_id = :p"), {"p": store}
            )
        ).scalar_one()

    with sentencias_capturadas(app_engine) as capturadas:
        res = await client.get(
            "/users/",
            headers=auth_headers(token),
            params={"role": "client", "q": q},
        )
    assert res.status_code == 200, res.text

    busqueda = [
        (sql, params)
        for sql, params in capturadas
        if "FROM users" in sql and "LIKE" in sql.upper()
    ]
    assert len(busqueda) == 1, [sql for sql, _ in capturadas]
    plan = await plan_de(app_engine, busqueda[0], store_id=str(store_id))

    assert "users" not in escaneos_secuenciales(plan), resumen(plan)
    condiciones = condiciones_de_indice(plan)
    assert any("store_id" in cond for cond in condiciones.values()), resumen(plan)
