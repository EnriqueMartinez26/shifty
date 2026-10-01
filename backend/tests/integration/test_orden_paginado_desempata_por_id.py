"""El listado de usuarios y el de tiendas del superadmin desempatan por id.

2026-10-01. Sintoma: con created_at empatado, el offset repetia o salteaba
filas entre paginas. ``UserRepository.get_all`` y
``StoreAdminRepository.list_stores`` ordenaban solo por ``created_at DESC``:
dos filas del mismo instante no tienen orden definido y cada pagina (otra
sentencia con otro ``OFFSET``) puede devolverlas en otro orden. El arreglo
copia el de ``services/repository.py``: el id (ULID) desempata.

SQLite no reproduce la repeticion: su ordenamiento deja los empates en el
orden de insercion y las paginas salen consistentes. Lo que si prueba es que
el orden queda definido por el id (descendente, como ``created_at``); sin el
desempate las filas salen en orden de insercion (ascendente) y el test falla.
La repeticion entre paginas se prueba contra Postgres en
``tests/postgres/test_pg_orden_paginado_desempata_por_id.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import ulid
from sqlalchemy.ext.asyncio import AsyncSession

from modules.stores.model import Store
from modules.superadmin.repository import StoreAdminRepository
from modules.users.model import User, UserRole
from modules.users.repository import UserRepository

INSTANTE = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
FILAS = 7
POR_PAGINA = 3


def ids_crecientes(cantidad: int) -> list[str]:
    """ULIDs ordenados: se insertan en orden creciente a proposito."""
    return sorted(str(ulid.ULID()) for _ in range(cantidad))


async def sembrar_empate(session: AsyncSession) -> tuple[str, list[str], list[str]]:
    """Tiendas y clientes con el MISMO created_at; devuelve sus ids.

    Devuelve ``(tienda_de_los_clientes, ids_de_clientes, ids_de_tiendas)``.
    La sesion tiene que poder escribir en cualquier tienda (en Postgres, con
    el contexto de superadmin ya aplicado).
    """
    ids_de_tiendas = ids_crecientes(FILAS)
    for indice, store_id in enumerate(ids_de_tiendas):
        session.add(
            Store(
                id=store_id,
                public_id=store_id,
                name=f"Tienda empate {indice}",
                slug=f"empate-{indice}",
                theme_config={"business_type": "general"},
                created_at=INSTANTE,
            )
        )
    await session.flush()

    tienda = ids_de_tiendas[0]
    ids_de_clientes = ids_crecientes(FILAS)
    for indice, user_id in enumerate(ids_de_clientes):
        session.add(
            User(
                id=user_id,
                email=f"empate-{indice}@test.com",
                hashed_password="x",
                first_name="Cliente",
                last_name=str(indice),
                role=UserRole.CLIENT,
                store_id=tienda,
                created_at=INSTANTE,
            )
        )
    await session.flush()
    await session.commit()
    return tienda, ids_de_clientes, ids_de_tiendas


async def paginas_de_usuarios(session: AsyncSession, tienda: str) -> list[str]:
    repo = UserRepository(session)
    vistos: list[str] = []
    for offset in range(0, FILAS, POR_PAGINA):
        pagina = await repo.get_all(tienda, limit=POR_PAGINA, offset=offset)
        vistos.extend(str(usuario.id) for usuario in pagina)
    return vistos


async def paginas_de_tiendas(session: AsyncSession) -> list[str]:
    repo = StoreAdminRepository(session)
    vistos: list[str] = []
    for offset in range(0, FILAS, POR_PAGINA):
        pagina = await repo.list_stores(
            search=None,
            is_active=None,
            has_subscription=None,
            limit=POR_PAGINA,
            offset=offset,
        )
        vistos.extend(str(fila["public_id"]) for fila in pagina)
    return vistos


@pytest.mark.asyncio
async def test_usuarios_con_created_at_empatado_salen_ordenados_por_id(
    test_session: AsyncSession,
) -> None:
    tienda, ids_de_clientes, _ = await sembrar_empate(test_session)

    vistos = await paginas_de_usuarios(test_session, tienda)

    assert vistos == sorted(ids_de_clientes, reverse=True)


@pytest.mark.asyncio
async def test_tiendas_con_created_at_empatado_salen_ordenadas_por_id(
    test_session: AsyncSession,
) -> None:
    _, _, ids_de_tiendas = await sembrar_empate(test_session)

    vistos = await paginas_de_tiendas(test_session)

    assert vistos == sorted(ids_de_tiendas, reverse=True)
