"""Esperar mas de `lock_timeout` por el FOR UPDATE responde 409, no 500.

AUD2-B7-02 (2026-09-20). La migracion `app_role_timeouts` le pone al rol de la
app `lock_timeout = '5s'`. Cuando varias reservas compiten por el mismo
profesional, la que espera mas de ese plazo por el `SELECT ... FOR UPDATE`
recibe SQLSTATE 55P03 (`lock_not_available`), que SQLAlchemy envuelve en
`DBAPIError`. S-18 mapeo 40P01 y 40001 a 409 neutro y dejo 55P03 afuera, asi
que esa espera salia como 500: un 5xx alcanzable en la prueba de rafaga sin
que nadie hubiera hecho nada mal (CLAUDE.md §4 exige cero 5xx ahi).

En SQLite no hay locks de fila ni `lock_timeout`: solo se prueba contra
Postgres. En vez de una rafaga con suficientes waiters como para pasar los 5
segundos -lenta y no determinista-, aca el lock lo retiene el rol dueno desde
afuera, asi que el 55P03 es seguro.
"""

import asyncio

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.postgres.test_pg_reserva_concurrente import _reserva, _tienda_reservable

pytestmark = pytest.mark.postgres

# lock_timeout es 5s; 30s deja margen sin colgar la suite si la guarda cambia.
ESPERA_MAXIMA_SEGUNDOS = 30


@pytest.mark.asyncio
async def test_esperar_el_lock_del_profesional_responde_409_neutro(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, service, staff, slot = await _tienda_reservable(
        client, app_sessions, "lock-timeout"
    )

    async with owner_engine.connect() as retenedor:
        # El rol dueno retiene la fila del profesional: la reserva se queda
        # esperando el mismo FOR UPDATE hasta que salta lock_timeout.
        await retenedor.execute(
            text("SELECT id FROM staff WHERE public_id = :p FOR UPDATE"),
            {"p": staff},
        )
        res: Response = await asyncio.wait_for(
            client.post(
                "/public/appointments",
                json=_reserva(store, service, staff, slot, 1, "pg-lock-timeout-01"),
            ),
            timeout=ESPERA_MAXIMA_SEGUNDOS,
        )
        await retenedor.rollback()

    assert res.status_code == 409, res.text
    cuerpo = res.json()
    assert cuerpo["error_code"] == "CONCURRENT_MODIFICATION", res.text
    # Regla 20: nada del driver ni del SQL hacia afuera.
    assert "SELECT" not in res.text and "55P03" not in res.text
    assert res.headers.get("cache-control") == "no-store"
