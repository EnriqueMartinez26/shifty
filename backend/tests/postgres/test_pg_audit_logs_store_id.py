"""``audit_logs.store_id``: upgrade con backfill y downgrade reales (B3-11).

2026-09-18, hallazgo B3-11: el listado de auditoria de una tienda filtraba en
Python sobre una ventana global y podia mostrar 0 eventos existiendo. La
migracion ``c5e7a9b1d3f4`` agrega la columna y la rellena desde el recurso
auditado. Las tablas de origen (``stores``, ``users``) tienen RLS forzada: el
backfill fija ``app.is_global_admin`` local a su transaccion para leerlas
completas aunque el rol que migra no sea superusuario.

Corre alembic como el deploy (proceso aparte, rol dueno) y deja la base en
head al terminar, pase lo que pase: el esquema es de alcance de sesion.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.postgres.conftest import alembic, seed_store_and_admin

pytestmark = pytest.mark.postgres

REVISION = "c5e7a9b1d3f4"
ANTERIOR = "a1c3e5b7d9f2"
CONTEXTO = "b3-11-pg"


async def _migrar(owner_engine: AsyncEngine, *args: str) -> None:
    resultado = alembic(*args)
    assert resultado.returncode == 0, resultado.stderr[-2000:]
    # Conexiones nuevas despues de cada ALTER (asyncpg cachea el esquema).
    await owner_engine.dispose()


async def _tiene_columna(owner_engine: AsyncEngine) -> bool:
    async with owner_engine.connect() as conn:
        total = (
            await conn.execute(
                text(
                    "select count(*) from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'audit_logs' "
                    "and column_name = 'store_id'"
                )
            )
        ).scalar_one()
    return int(total) == 1


@pytest.mark.asyncio
async def test_upgrade_rellena_store_id_y_downgrade_lo_quita(
    owner_engine: AsyncEngine,
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    store_id = await seed_store_and_admin(
        app_sessions, slug="b3-11-pg", email="b3-11-pg@demo.com"
    )
    assert await _tiene_columna(owner_engine)

    try:
        await _migrar(owner_engine, "downgrade", ANTERIOR)
        assert not await _tiene_columna(owner_engine)

        async with owner_engine.begin() as conn:
            # El dueno tambien esta sujeto a la RLS forzada de users.
            await conn.execute(
                text("select set_config('app.is_global_admin', 'true', true)")
            )
            user_id = (
                await conn.execute(
                    text("select id from users where email = 'b3-11-pg@demo.com'")
                )
            ).scalar_one()
            for tipo, recurso in (
                ("Store", store_id),
                ("User", user_id),
                ("Plan", "plan-global"),
                ("User", "usuario-borrado"),
            ):
                await conn.execute(
                    text(
                        "insert into audit_logs "
                        "(resource_type, resource_id, action, context) "
                        "values (:t, :r, 'update', :ctx)"
                    ),
                    {"t": tipo, "r": recurso, "ctx": CONTEXTO},
                )

        await _migrar(owner_engine, "upgrade", REVISION)
        assert await _tiene_columna(owner_engine)
        async with owner_engine.connect() as conn:
            filas = {
                (tipo, recurso): tienda
                for tipo, recurso, tienda in (
                    await conn.execute(
                        text(
                            "select resource_type, resource_id, store_id "
                            "from audit_logs where context = :ctx"
                        ),
                        {"ctx": CONTEXTO},
                    )
                ).all()
            }
            indices = {
                fila[0]
                for fila in (
                    await conn.execute(
                        text(
                            "select indexname from pg_indexes "
                            "where tablename = 'audit_logs'"
                        )
                    )
                ).all()
            }
        assert filas == {
            ("Store", store_id): store_id,
            ("User", user_id): store_id,
            ("Plan", "plan-global"): None,
            ("User", "usuario-borrado"): None,
        }
        assert "ix_audit_logs_store_id" in indices

        # audit_logs sigue fuera de RLS: el rol de la app la lee sin contexto.
        async with owner_engine.connect() as conn:
            rls = (
                await conn.execute(
                    text(
                        "select relrowsecurity from pg_class "
                        "where relname = 'audit_logs'"
                    )
                )
            ).scalar_one()
        assert rls is False

        await _migrar(owner_engine, "downgrade", ANTERIOR)
        assert not await _tiene_columna(owner_engine)
        async with owner_engine.connect() as conn:
            quedan = (
                await conn.execute(
                    text("select count(*) from audit_logs where context = :ctx"),
                    {"ctx": CONTEXTO},
                )
            ).scalar_one()
        assert quedan == 4, "el downgrade no puede borrar filas"
    finally:
        await _migrar(owner_engine, "upgrade", "head")

    assert await _tiene_columna(owner_engine)
