"""Dos locks de varios profesionales en orden inverso no hacen deadlock (S-11).

``lock_staff_rows`` lockea en orden total por id con una sola sentencia, sin
importar el orden en que le lleguen los ids. Antes el alta de bloqueos
lockeaba de a uno en el orden de ``_staff_for`` (sin ORDER BY): dos
transacciones con los mismos profesionales en orden distinto se esperaban en
ciclo y Postgres abortaba una. En SQLite no hay locks de fila; esto solo se
prueba contra Postgres.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import tenant_bypass
from modules.appointments.repository import AppointmentRepository
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres


async def _tres_profesionales(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, list[str]]:
    _store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, token)
    staff = [
        await create_staff(client, token, service, email=f"p{i}-{slug}@demo.com")
        for i in range(3)
    ]
    return token, staff


@pytest.mark.asyncio
async def test_lock_de_varios_profesionales_en_orden_inverso_sin_deadlock(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    _token, staff = await _tres_profesionales(client, app_sessions, "orden-lock")
    ambas_arrancaron = asyncio.Barrier(2)

    async def lockear(ids: list[str]) -> str:
        async with app_sessions() as db:
            async with tenant_bypass(db):
                await ambas_arrancaron.wait()
                await AppointmentRepository(db).lock_staff_rows(ids)
                # Retiene los locks un rato para que la otra quede esperando.
                await asyncio.sleep(0.3)
                await db.commit()
                return "ok"

    resultados = await asyncio.wait_for(
        asyncio.gather(lockear(staff), lockear(list(reversed(staff)))),
        timeout=30,
    )

    assert list(resultados) == ["ok", "ok"]


@pytest.mark.asyncio
async def test_dos_cierres_de_tienda_simultaneos_terminan_bien(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    token, _staff = await _tres_profesionales(client, app_sessions, "cierres")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    inicio = dia.replace(hour=13, minute=0, second=0, microsecond=0)

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/appointment-blocks/store-wide",
                headers=auth_headers(token),
                json={
                    "starts_at": (inicio + timedelta(hours=i)).isoformat(),
                    "ends_at": (inicio + timedelta(hours=i + 1)).isoformat(),
                    "reason": f"Cierre {i}",
                },
            )
            for i in range(4)
        )
    )

    assert [r.status_code for r in respuestas] == [201] * 4, [
        r.text[:200] for r in respuestas
    ]
