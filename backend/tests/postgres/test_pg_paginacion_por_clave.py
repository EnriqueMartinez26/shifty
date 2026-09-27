"""F3-08 (plan de rendimiento, R7-11): la pagina por clave no usa OFFSET.

2026-09-24. ``/appointments/search`` pagina con ``OFFSET (page - 1) *
page_size`` (hasta ~1 M): la base recorre y descarta todo lo saltado. Con
``after`` la sentencia de la pagina no lleva ``OFFSET`` y el plan entra por el
indice ``(store_id, starts_at)`` con la cota ``starts_at <= clave`` como
``Index Cond`` (bajo RLS, solo los predicados leakproof llegan al indice: por
eso la cota va escrita sola y no como comparacion de filas).

Se siembra historia en dos tiendas (para que el filtro de tienda pese), se
corre ``ANALYZE`` y se explica la sentencia REAL como ``shifty_app``.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login
from tests.postgres.planes import (
    condiciones_de_indice,
    nodos,
    plan_de,
    resumen,
    sentencias_capturadas,
)
from tests.postgres.test_pg_cohortes_acotadas import sembrar_historia

pytestmark = pytest.mark.postgres


async def _tienda_con_historia(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    slug: str,
) -> tuple[str, str]:
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    await sembrar_historia(owner_engine, store, service, staff, prefijo=slug)
    return store, token


@pytest.mark.asyncio
async def test_la_pagina_por_clave_entra_por_el_indice_sin_offset(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
) -> None:
    store, token = await _tienda_con_historia(
        client, app_sessions, owner_engine, "pg-clave"
    )
    await _tienda_con_historia(client, app_sessions, owner_engine, "pg-clave-otra")

    primera = await client.get(
        "/appointments/search",
        params={"page_size": 50},
        headers=auth_headers(token),
    )
    assert primera.status_code == 200, primera.text
    cursor = primera.json()["next_cursor"]
    assert cursor
    with sentencias_capturadas(app_engine) as capturadas:
        segunda = await client.get(
            "/appointments/search",
            params={"page_size": 50, "after": cursor, "include_total": "false"},
            headers=auth_headers(token),
        )
    assert segunda.status_code == 200, segunda.text
    assert len(segunda.json()["results"]) == 50

    paginas = [s for s in capturadas if "FROM appointments" in s[0]]
    assert len(paginas) == 1, [s[0] for s in capturadas]
    sql = paginas[0][0]
    assert "OFFSET" not in sql.upper(), sql
    plan = await plan_de(app_engine, paginas[0], store_id=store)
    assert any(nodo.get("Node Type") == "Limit" for nodo in nodos(plan)), resumen(plan)
    condicion = condiciones_de_indice(plan).get("ix_appointments_store_starts_at", "")
    assert "store_id" in condicion and "starts_at <=" in condicion, resumen(plan)
