"""AUD2-B6-03 (2026-09-20): la terna de sena se validaba SOLO en la entrada.

Sintoma: nada impedia que una fila de ``services`` tuviera una terna
imposible. Dos casos llegaron a la base antes de la validacion de entrada
(B6-02) y siguieron ahi despues, porque un PATCH que no toca la sena no se
bloquea: ``percent`` con monto 500 le cobraba al cliente 5 veces el precio
por adelantado, y ``required`` sin monto reservaba sin cobrar. Un tercer
camino los reintroduce: dos PATCH concurrentes sobre el mismo servicio
validan cada uno contra el snapshot que leyo sin lock y el ultimo escribe
encima.

Lo que toca dinero se garantiza con algo determinista en la base, no con un
validador de Pydantic: estos CHECK son el mismo criterio que
``deposit_policy_error``, aplicado a todo lo que escribe en ``services``.

La prueba real corre contra Postgres (``tests/postgres/test_pg_sena_check.py``);
aca se verifica que la guarda existe en el modelo, que es de donde sale el
esquema.
"""

import pytest
import ulid
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.services.model import Service
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)


async def _store_id(client: AsyncClient, session: AsyncSession, slug: str) -> str:
    await register_and_login(client, slug=slug, email=f"{slug}@example.com")
    resultado = await session.execute(select(Store.id).where(Store.slug == slug))
    return str(resultado.scalar_one())


def _servicio(store_id: str, **sena: object) -> Service:
    servicio_id = str(ulid.ULID())
    return Service(
        id=servicio_id,
        public_id=servicio_id,
        store_id=store_id,
        name="Corte",
        duration_minutes=30,
        price=10000,
        **sena,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sena",
    [
        # Un porcentaje mayor a 100 cobra mas que el servicio.
        {"deposit_mode": "required", "deposit_type": "percent", "deposit_amount": 500},
        {"deposit_mode": "optional", "deposit_type": "percent", "deposit_amount": 101},
        # Sena obligatoria (u opcional) sin monto: importe 0, no cobra nada.
        {"deposit_mode": "required", "deposit_type": "percent", "deposit_amount": None},
        {"deposit_mode": "required", "deposit_type": "fixed", "deposit_amount": 0},
        {"deposit_mode": "optional", "deposit_type": "fixed", "deposit_amount": None},
    ],
)
async def test_la_base_rechaza_una_terna_de_sena_imposible(
    client: AsyncClient, test_session: AsyncSession, sena: dict[str, object]
) -> None:
    store_id = await _store_id(
        client, test_session, f"b6-03-{ulid.ULID()}".lower()[:40]
    )
    test_session.add(_servicio(store_id, **sena))
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sena",
    [
        # Sin sena no hay monto que validar.
        {"deposit_mode": "none", "deposit_type": "percent", "deposit_amount": None},
        {"deposit_mode": "none", "deposit_type": "fixed", "deposit_amount": None},
        # `full` es el precio entero: no necesita monto.
        {"deposit_mode": "required", "deposit_type": "full", "deposit_amount": None},
        # Los bordes validos siguen entrando.
        {"deposit_mode": "required", "deposit_type": "percent", "deposit_amount": 100},
        {"deposit_mode": "optional", "deposit_type": "fixed", "deposit_amount": 0.01},
    ],
)
async def test_las_ternas_validas_siguen_entrando(
    client: AsyncClient, test_session: AsyncSession, sena: dict[str, object]
) -> None:
    """El CHECK no puede rechazar nada que el schema de entrada acepta."""
    store_id = await _store_id(
        client, test_session, f"b6-03-ok-{ulid.ULID()}".lower()[:40]
    )
    servicio = _servicio(store_id, **sena)
    test_session.add(servicio)
    await test_session.commit()
    guardado = await test_session.execute(
        select(Service.public_id).where(Service.id == servicio.id)
    )
    assert guardado.scalar_one() == servicio.public_id
