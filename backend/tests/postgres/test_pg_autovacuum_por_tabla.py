"""F1-16 (plan de rendimiento, R7-07): autovacuum afinado por tabla.

2026-09-24. Con los valores por defecto (20 % de filas muertas para VACUUM) una
tabla de un millon de turnos esperaba 200.000 UPDATE para limpiarse, y el
outbox/inbox -que se escriben y marcan todo el tiempo- acumulaban bloat entre
corridas. Los parametros van por tabla (``ALTER TABLE ... SET``, lock
``SHARE UPDATE EXCLUSIVE``: no frena la app) y el downgrade los resetea.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.postgres

ESPERADO = {
    "appointments": {
        "autovacuum_vacuum_scale_factor=0.05",
        "autovacuum_analyze_scale_factor=0.02",
    },
    "outbox_messages": {
        "autovacuum_vacuum_scale_factor=0.01",
        "autovacuum_vacuum_threshold=500",
        "autovacuum_vacuum_insert_scale_factor=0.05",
    },
    "webhook_inbox": {
        "autovacuum_vacuum_scale_factor=0.01",
        "autovacuum_vacuum_threshold=500",
        "autovacuum_vacuum_insert_scale_factor=0.05",
    },
    "notifications": {"autovacuum_vacuum_insert_scale_factor=0.05"},
    "audit_logs": {"autovacuum_vacuum_insert_scale_factor=0.05"},
}


@pytest.mark.asyncio
async def test_cada_tabla_que_crece_tiene_su_autovacuum(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.connect() as conn:
        opciones = {
            fila[0]: set(fila[1] or [])
            for fila in (
                await conn.execute(
                    text(
                        "select relname, reloptions from pg_class "
                        "where relname = any(:tablas) and relkind = 'r'"
                    ),
                    {"tablas": list(ESPERADO)},
                )
            ).all()
        }
    faltan = {
        tabla: sorted(esperadas - opciones.get(tabla, set()))
        for tabla, esperadas in ESPERADO.items()
        if not esperadas <= opciones.get(tabla, set())
    }
    assert not faltan, faltan
