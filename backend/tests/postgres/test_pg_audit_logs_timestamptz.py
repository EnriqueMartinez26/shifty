"""``audit_logs.created_at`` es timestamptz y la migracion conserva el instante (B5-13).

2026-09-18, hallazgo B5-13: la columna era ``timestamp without time zone``
con ``server_default now()``, la unica naive del esquema (regla 24). La
migracion ``a1c3e5b7d9f2`` la convierte con ``created_at AT TIME ZONE 'UTC'``:
un valor escrito ANTES de migrar (hora de pared UTC) tiene que seguir siendo
el mismo instante despues del ``upgrade``, y el ``downgrade`` tiene que
devolver exactamente la hora de pared original (regla 13: ambos sentidos
reales).

Corre alembic como el deploy (proceso aparte, rol dueno) y deja la base en
head al terminar, pase lo que pase: el esquema es de alcance de sesion.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.postgres.conftest import alembic

pytestmark = pytest.mark.postgres

REVISION = "a1c3e5b7d9f2"
ANTERIOR = "f8c0e2a4b6d8"
# Hora de pared UTC guardada por el esquema viejo: 15/09 22:30 ART.
PARED_UTC = datetime(2026, 9, 16, 1, 30)
CONTEXTO = "b5-13-pg"


async def _tipo(owner_engine: AsyncEngine) -> str:
    async with owner_engine.connect() as conn:
        tipo = (
            await conn.execute(
                text(
                    "select data_type from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'audit_logs' "
                    "and column_name = 'created_at'"
                )
            )
        ).scalar_one()
    return str(tipo)


async def _valor(owner_engine: AsyncEngine) -> datetime:
    async with owner_engine.connect() as conn:
        valor = (
            await conn.execute(
                text("select created_at from audit_logs where context = :ctx"),
                {"ctx": CONTEXTO},
            )
        ).scalar_one()
    assert isinstance(valor, datetime)
    return valor


async def _migrar(owner_engine: AsyncEngine, *args: str) -> None:
    resultado = alembic(*args)
    assert resultado.returncode == 0, resultado.stderr[-2000:]
    # asyncpg cachea sentencias preparadas con el tipo viejo de la columna:
    # conexiones nuevas despues de cada ALTER.
    await owner_engine.dispose()


@pytest.mark.asyncio
async def test_created_at_es_timestamptz_y_el_upgrade_conserva_el_instante(
    owner_engine: AsyncEngine,
) -> None:
    assert await _tipo(owner_engine) == "timestamp with time zone"

    try:
        await _migrar(owner_engine, "downgrade", ANTERIOR)
        assert await _tipo(owner_engine) == "timestamp without time zone"
        async with owner_engine.begin() as conn:
            # Una sesion con otra zona no cambia lo que se guarda en una
            # columna naive, ni lo que el USING interpreta despues.
            await conn.execute(text("set time zone 'America/Argentina/Buenos_Aires'"))
            await conn.execute(
                text(
                    "insert into audit_logs "
                    "(created_at, resource_type, resource_id, action, context) "
                    "values (:ts, 'Store', 'b513', 'update', :ctx)"
                ),
                {"ts": PARED_UTC, "ctx": CONTEXTO},
            )
        assert await _valor(owner_engine) == PARED_UTC

        await _migrar(owner_engine, "upgrade", REVISION)
        assert await _tipo(owner_engine) == "timestamp with time zone"
        assert await _valor(owner_engine) == PARED_UTC.replace(tzinfo=timezone.utc)

        async with owner_engine.connect() as conn:
            indices = {
                r[0]
                for r in (
                    await conn.execute(
                        text(
                            "select indexname from pg_indexes "
                            "where tablename = 'audit_logs'"
                        )
                    )
                ).all()
            }
        assert "ix_audit_logs_created_at" in indices

        # El default now() sigue funcionando y ahora devuelve un instante.
        async with owner_engine.begin() as conn:
            nuevo = (
                await conn.execute(
                    text(
                        "insert into audit_logs "
                        "(resource_type, resource_id, action, context) "
                        "values ('Store', 'b513', 'update', 'b5-13-pg-nuevo') "
                        "returning created_at"
                    )
                )
            ).scalar_one()
        assert nuevo.tzinfo is not None
        assert abs((datetime.now(timezone.utc) - nuevo).total_seconds()) < 300

        await _migrar(owner_engine, "downgrade", ANTERIOR)
        assert await _tipo(owner_engine) == "timestamp without time zone"
        assert await _valor(owner_engine) == PARED_UTC
    finally:
        await _migrar(owner_engine, "upgrade", "head")

    assert await _tipo(owner_engine) == "timestamp with time zone"
