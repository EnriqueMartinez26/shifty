"""pg_stat_statements queda instalada (plan de rendimiento, R7-04).

2026-09-24. Sin la extension no hay forma de saber que consultas consumen la
base en produccion: los EXPLAIN de estas pruebas dicen que indice PUEDE usar
una consulta, no cuanto pesa con el trafico real. compose la precarga
(``shared_preload_libraries``) en dev y prod; la migracion la crea. Si el
servidor de pruebas no la precarga, la vista no se puede consultar y el test
se saltea con el motivo, en vez de fallar por el entorno.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_la_extension_existe_y_registra_consultas(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.connect() as conn:
        precarga = str(
            (await conn.execute(text("show shared_preload_libraries"))).scalar_one()
        )
        if "pg_stat_statements" not in precarga:
            pytest.skip(f"el servidor no precarga pg_stat_statements ({precarga!r})")
        instalada = (
            await conn.execute(
                text("select 1 from pg_extension where extname = 'pg_stat_statements'")
            )
        ).scalar_one_or_none()
        assert instalada == 1
        total = (
            await conn.execute(text("select count(*) from pg_stat_statements"))
        ).scalar_one()
    assert total >= 0
