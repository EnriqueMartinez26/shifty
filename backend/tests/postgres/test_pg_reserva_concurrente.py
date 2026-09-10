"""Rafagas concurrentes de reserva publica sobre el MISMO turno.

Prueba lo que ninguna secuencia de requests puede probar: que el lock
pesimista sobre el profesional + la exclusion GiST dejan pasar UNA reserva
y rechazan el resto con 409, sin ningun 5xx y sin dos filas activas en la
base. Corre con una sesion por request contra Postgres real; en SQLite el
mismo test seria una mentira (no hay concurrencia ni exclusion).
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from typing import cast
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))


async def _tienda_reservable(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str, str, datetime]:
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)
    return store, service, staff, slot


def _reserva(
    store: str, service: str, staff: str, slot: datetime, i: int, key: str
) -> dict[str, str]:
    return {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": f"Cliente {i}",
        "client_phone": f"+54911555{i:05d}",
        "idempotency_key": key,
    }


async def _turnos_activos(owner_engine: AsyncEngine, staff: str) -> int:
    async with owner_engine.connect() as conn:
        total = (
            await conn.execute(
                text(
                    "select count(*) from appointments "
                    "where staff_id = :staff "
                    "and status in ('pending','pending_payment','confirmed')"
                ),
                {"staff": staff},
            )
        ).scalar_one()
        return cast(int, total)


@pytest.mark.asyncio
async def test_rafaga_mismo_slot_deja_pasar_una_sola_reserva(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, service, staff, slot = await _tienda_reservable(
        client, app_sessions, "rafaga"
    )

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/public/appointments",
                json=_reserva(store, service, staff, slot, i, f"pg-rafaga-{i:02d}"),
            )
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(201) == 1, codigos
    assert set(codigos) <= {201, 409}, codigos
    assert await _turnos_activos(owner_engine, staff) == 1


@pytest.mark.asyncio
async def test_rafaga_con_la_misma_idempotency_key_crea_un_solo_turno(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    # Reintentos de red: el mismo cliente manda 30 veces la misma reserva.
    store, service, staff, slot = await _tienda_reservable(client, app_sessions, "idem")
    cuerpo = _reserva(store, service, staff, slot, 1, "idem-misma-clave")

    respuestas = await asyncio.gather(
        *(client.post("/public/appointments", json=cuerpo) for _ in range(30))
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    creados = {r.json()["public_id"] for r in respuestas if r.status_code == 201}
    assert len(creados) <= 1, creados
    assert await _turnos_activos(owner_engine, staff) == 1


@pytest.mark.asyncio
async def test_slots_distintos_no_se_bloquean_entre_si(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    # El lock es por profesional, no global: N slots distintos en paralelo
    # deben entrar todos (el servicio dura 30 minutos).
    store, service, staff, slot = await _tienda_reservable(
        client, app_sessions, "paralelo"
    )
    slots = [slot + timedelta(minutes=30 * i) for i in range(6)]

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/public/appointments",
                json=_reserva(store, service, staff, s, i, f"pg-paralelo-{i:02d}"),
            )
            for i, s in enumerate(slots)
        )
    )
    codigos = [r.status_code for r in respuestas]

    assert codigos == [201] * len(slots), [
        (c, r.text[:120]) for c, r in zip(codigos, respuestas)
    ]
    assert await _turnos_activos(owner_engine, staff) == len(slots)
