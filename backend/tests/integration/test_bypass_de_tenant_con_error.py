"""Un error dentro de ``tenant_bypass`` sale tal cual y sin dejar el bypass puesto.

Revision V-diff de B3-13, 2026-09-18. Sintoma: ``tenant_bypass`` era un
``try/finally`` que a la salida SIEMPRE hacia ``_apply_tenant_context``, y eso
llama a ``await session.connection()``. Si dentro del bloque fallaba un
``flush``/``commit`` la sesion queda en estado "necesita rollback" y
``connection()`` levanta ``PendingRollbackError`` (en Postgres, un ``execute``
fallido deja ``InFailedSQLTransaction`` en el ``set_config``). Ese error
secundario reemplazaba al original: un ``IntegrityError`` que ``main.py`` mapea
a 409 salia como 500. El ``finally`` de antes de B3-13 no tocaba la conexion;
el hueco lo abrio el propio helper.

Ademas, en cualquier camino con excepcion los ContextVars tienen que quedar en
``(None, False)``: el bypass no puede sobrevivir al bloque.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    _current_store_id,
    _is_global_admin,
    set_tenant_context,
    tenant_bypass,
)
from modules.billing.model import Plan


@pytest.fixture(autouse=True)
def _contexto_limpio() -> Iterator[None]:
    set_tenant_context(None, False)
    yield
    set_tenant_context(None, False)


def _contexto() -> tuple[str | None, bool]:
    return _current_store_id.get(), _is_global_admin.get()


@pytest.mark.asyncio
async def test_una_integrity_error_adentro_sale_como_integrity_error(
    test_session: AsyncSession,
) -> None:
    test_session.add(Plan(name="Plan Duplicado", price=Decimal("1")))
    await test_session.commit()

    with pytest.raises(IntegrityError):
        async with tenant_bypass(test_session):
            test_session.add(Plan(name="Plan Duplicado", price=Decimal("2")))
            await test_session.flush()

    assert _contexto() == (None, False), "el bypass sobrevivio a la excepcion"

    # La sesion quedo usable: el rollback del camino con error ya corrio.
    total = await test_session.execute(select(func.count()).select_from(Plan))
    assert total.scalar_one() == 1


@pytest.mark.asyncio
async def test_un_error_de_negocio_adentro_resetea_el_contexto(
    test_session: AsyncSession,
) -> None:
    with pytest.raises(LookupError, match="no existe"):
        async with tenant_bypass(test_session):
            assert _contexto() == (None, True)
            raise LookupError("no existe")

    assert _contexto() == (None, False)


@pytest.mark.asyncio
async def test_el_camino_feliz_sigue_bajando_el_bypass_a_la_salida(
    test_session: AsyncSession,
) -> None:
    async with tenant_bypass(test_session):
        test_session.add(Plan(name="Plan Feliz", price=Decimal("1")))
        await test_session.commit()

    assert _contexto() == (None, False)
    total = await test_session.execute(select(func.count()).select_from(Plan))
    assert total.scalar_one() == 1
