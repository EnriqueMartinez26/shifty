"""Despues de un bloque de bypass, la conexion ya no bypassea RLS.

Auditoria B3-13, 2026-09-17. Sintoma: los nueve bloques de bypass reseteaban
el ContextVar en el ``finally`` pero no lo bajaban a la conexion. Como
``TenantSession.commit`` reaplica el contexto VIGENTE al momento del commit --
dentro del bloque, el de bypass --, la transaccion que queda abierta despues
del commit conserva ``app.is_global_admin = true``. El ``finally`` cambiaba el
ContextVar y nada mas: cualquier ``execute`` posterior leia todas las tiendas.

En SQLite esto es invisible (``_apply_tenant_context`` retorna temprano), asi
que la prueba vive aca. Es la que le faltaba a ``test_pg_rls.py``: "despues del
bloque de bypass la conexion ya no bypassea".
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import set_tenant_context, tenant_bypass, _apply_tenant_context
from tests.postgres.conftest import seed_store_and_admin

pytestmark = pytest.mark.postgres


async def _bandera_de_admin(session: AsyncSession) -> str:
    valor = await session.execute(
        text("select current_setting('app.is_global_admin', true)")
    )
    return str(valor.scalar_one() or "")


async def _tienda_del_contexto(session: AsyncSession) -> str:
    valor = await session.execute(
        text("select current_setting('app.current_store_id', true)")
    )
    return str(valor.scalar_one() or "")


@pytest.mark.asyncio
async def test_la_conexion_deja_de_bypassear_al_salir_del_bloque(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    tienda_a = await seed_store_and_admin(
        app_sessions, slug="bypass-a", email="bypass-a@demo.com"
    )
    tienda_b = await seed_store_and_admin(
        app_sessions, slug="bypass-b", email="bypass-b@demo.com"
    )

    async with app_sessions() as session:
        set_tenant_context(tienda_a, False)
        await _apply_tenant_context(session)

        async with tenant_bypass(session):
            assert await _bandera_de_admin(session) == "true"
            # El commit de adentro es el que dejaba pegado el bypass: abre una
            # transaccion nueva con el contexto vigente (el de bypass).
            await session.commit()
            assert await _bandera_de_admin(session) == "true"

        # Fuera del bloque la conexion ya no bypassea.
        assert await _bandera_de_admin(session) != "true", (
            "la conexion salio del bloque con el bypass de RLS puesto"
        )
        assert await _tienda_del_contexto(session) in {"", "0"}

        # Y lo que se lea despues no puede ver las dos tiendas.
        visibles = await session.execute(text("select count(*) from stores"))
        assert visibles.scalar_one() == 0, (
            "sin contexto de tienda RLS tiene que esconder todas las filas; "
            f"las tiendas sembradas son {tienda_a} y {tienda_b}"
        )
        set_tenant_context(None, False)


@pytest.mark.asyncio
async def test_un_execute_fallido_adentro_sale_con_su_error_y_sin_bypass(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Revision V-diff, 2026-09-18: con la transaccion abortada, reaplicar el
    contexto a la salida levantaba ``InFailedSQLTransaction`` en el
    ``set_config`` y tapaba el error real. Tiene que salir el original."""
    async with app_sessions() as session:
        with pytest.raises(DBAPIError) as capturado:
            async with tenant_bypass(session):
                await session.execute(text("select 1 / 0"))

        assert "InFailedSQLTransaction" not in type(capturado.value.orig).__name__
        assert "division" in str(capturado.value.orig).lower()

        # El rollback del camino con error ya corrio: la sesion es usable y la
        # conexion no quedo con el bypass puesto.
        assert await _bandera_de_admin(session) != "true"
