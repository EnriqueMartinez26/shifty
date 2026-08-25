"""Contratos de arranque.

``ensure_runtime_contracts`` corre en el lifespan de la app y es lo que
garantiza que el esquema exista antes de atender la primera request. Nunca
estuvo cubierto: si rompe, la app no levanta.
"""

from typing import Any, AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from core.runtime_contracts import ensure_runtime_contracts


@pytest_asyncio.fixture
async def engine_vacio() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    yield engine
    await engine.dispose()


def _tablas(sync_conn: Any) -> list[str]:
    return list(inspect(sync_conn).get_table_names())


@pytest.mark.asyncio
async def test_crea_el_esquema_desde_cero(engine_vacio: AsyncEngine) -> None:
    await ensure_runtime_contracts(engine_vacio)

    async with engine_vacio.begin() as conn:
        tablas = set(await conn.run_sync(_tablas))

    # Un nucleo representativo de las tres areas del dominio.
    for esperada in ("stores", "appointments", "payments", "users", "notifications"):
        assert esperada in tablas, f"falta la tabla {esperada}"


@pytest.mark.asyncio
async def test_es_idempotente(engine_vacio: AsyncEngine) -> None:
    """Corre en cada arranque: dos ejecuciones seguidas no pueden fallar."""
    await ensure_runtime_contracts(engine_vacio)
    await ensure_runtime_contracts(engine_vacio)

    async with engine_vacio.begin() as conn:
        tablas = set(await conn.run_sync(_tablas))
    assert "appointments" in tablas


@pytest.mark.asyncio
async def test_repara_stores_sin_feature_flags(engine_vacio: AsyncEngine) -> None:
    """Migracion aditiva de rescate para bases viejas sin la columna."""
    async with engine_vacio.begin() as conn:
        await conn.execute(text("CREATE TABLE stores (id VARCHAR PRIMARY KEY)"))

    await ensure_runtime_contracts(engine_vacio)

    async with engine_vacio.begin() as conn:
        columnas = await conn.run_sync(
            lambda sync_conn: {
                c["name"] for c in inspect(sync_conn).get_columns("stores")
            }
        )
    assert "feature_flags" in columnas
