"""Paginar por offset con created_at empatado no repite ni saltea filas.

2026-10-01. Sintoma: con created_at empatado, el offset repetia o salteaba
filas entre paginas. ``UserRepository.get_all`` (``/users/``) y
``StoreAdminRepository.list_stores`` (``/superadmin/stores``) ordenaban solo
por ``created_at DESC``. En Postgres el orden de los empates no esta definido
y depende del plan: con ``LIMIT`` chico el sort es top-N heapsort, que para
distintos ``LIMIT + OFFSET`` deja los empates en distinto orden, asi que cada
pagina puede traer una fila que ya salio o esconder otra. El id (ULID)
desempata, como en ``services/repository.py``.

Se siembran tiendas y clientes con el MISMO ``created_at`` como ``shifty_app``
bajo contexto de superadmin y se recorren las paginas con el repositorio real.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import _apply_tenant_context, set_tenant_context
from tests.integration.test_orden_paginado_desempata_por_id import (
    paginas_de_tiendas,
    paginas_de_usuarios,
    sembrar_empate,
)

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_paginas_con_created_at_empatado_traen_cada_fila_una_vez(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with app_sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            tienda, ids_de_clientes, ids_de_tiendas = await sembrar_empate(session)

            usuarios = await paginas_de_usuarios(session, tienda)
            tiendas = await paginas_de_tiendas(session)
        finally:
            set_tenant_context(None, False)

    # Cada fila exactamente una vez...
    assert sorted(usuarios) == sorted(ids_de_clientes), usuarios
    assert sorted(tiendas) == sorted(ids_de_tiendas), tiendas
    # ...y en un orden estable: created_at DESC y, en el empate, id DESC.
    assert usuarios == sorted(ids_de_clientes, reverse=True)
    assert tiendas == sorted(ids_de_tiendas, reverse=True)
