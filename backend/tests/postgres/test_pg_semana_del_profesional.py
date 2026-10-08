"""Reemplazo de la semana del profesional en rafaga, contra Postgres real.

2026-10-08 (``PUT /staff/{public_id}/schedules``). Lo que SQLite no prueba:

- El ``DELETE`` + ``INSERT`` del reemplazo corre como ``shifty_app`` bajo RLS.
- Dos reemplazos a la vez sobre el mismo profesional no mezclan sus cuerpos.
  Sin el ``SELECT ... FOR UPDATE`` de la fila del profesional, en READ
  COMMITTED cada transaccion borraba solo las franjas que veia su foto y la
  semana terminaba con la union de los dos cuerpos.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = min(int(os.getenv("TEST_POSTGRES_RAFAGA", "25")), 10)


def _semana(i: int) -> dict[str, Any]:
    """Cuerpo distinguible: los minutos del cierre identifican al pedido."""
    return {
        "schedules": [
            {"day_of_week": 1, "start_time": "06:00:00", "end_time": f"08:{i:02d}:00"},
            {"day_of_week": 3, "start_time": "10:00:00", "end_time": f"12:{i:02d}:00"},
        ]
    }


@pytest.mark.asyncio
async def test_rafaga_de_reemplazos_deja_una_sola_semana_entera(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    _store, token = await register_and_login(
        client, app_sessions, slug="pg-semana", email="pg-semana@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-pg-semana@demo.com")

    respuestas = await asyncio.gather(
        *(
            client.put(
                f"/staff/{staff}/schedules",
                headers=auth_headers(token),
                json=_semana(i),
            )
            for i in range(RAFAGA)
        )
    )

    assert sorted(r.status_code for r in respuestas) == [200] * RAFAGA, [
        r.text for r in respuestas if r.status_code != 200
    ]
    async with owner_engine.connect() as conn:
        filas = (
            await conn.execute(
                text(
                    "select day_of_week, end_time from schedules "
                    "where staff_id = :staff order by day_of_week"
                ),
                {"staff": staff},
            )
        ).all()
    # Exactamente la semana de UN pedido: dos franjas con los mismos minutos.
    assert [fila.day_of_week for fila in filas] == [1, 3], filas
    assert len({fila.end_time.minute for fila in filas}) == 1, filas
