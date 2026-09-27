"""Rafagas del alta del panel para un cliente (FF-04) contra Postgres real.

2026-09-24. ``POST /appointments/`` con ``client_name`` + ``client_phone``
sigue el camino del portal: lock del profesional, relectura de bloqueo y
choque bajo el lock, INSERT, y la exclusion GiST como ultima defensa. Lo que
una secuencia de requests no prueba (CLAUDE.md §4): N altas sobre el MISMO
slot dejan una, el resto 409 y cero 5xx; N con la misma clave crean un solo
turno; y la seleccion de "cualquier profesional" llena cada agenda una vez.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))


async def _panel(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    slug: str,
    profesionales: int = 1,
) -> tuple[dict[str, str], str, list[str], datetime]:
    _store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, token)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    staffs = []
    for i in range(profesionales):
        staff = await create_staff(
            client, token, service, email=f"pro{i}-{slug}@demo.com"
        )
        await add_staff_schedule(client, token, staff, target_date=dia)
        staffs.append(staff)
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)
    return auth_headers(token), service, staffs, slot


def _alta(
    service: str, staff: str | None, slot: datetime, i: int, key: str
) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {
        "service_id": service,
        "starts_at": slot.isoformat(),
        "client_name": f"Cliente {i}",
        "client_phone": f"+54911777{i:05d}",
        "idempotency_key": key,
    }
    if staff is not None:
        cuerpo["staff_id"] = staff
    return cuerpo


async def _activos(owner_engine: AsyncEngine, staff: str) -> int:
    async with owner_engine.connect() as conn:
        total = (
            await conn.execute(
                text(
                    "select count(*) from appointments where staff_id = :staff "
                    "and status in ('pending','pending_payment','confirmed')"
                ),
                {"staff": staff},
            )
        ).scalar_one()
        return cast(int, total)


@pytest.mark.asyncio
async def test_rafaga_del_panel_sobre_el_mismo_slot_deja_una(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    headers, service, staffs, slot = await _panel(client, app_sessions, "panelraf")

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/appointments/",
                headers=headers,
                json=_alta(service, staffs[0], slot, i, f"panel-rafaga-{i:02d}"),
            )
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(201) == 1, codigos
    assert codigos.count(409) == RAFAGA - 1, codigos
    assert await _activos(owner_engine, staffs[0]) == 1


@pytest.mark.asyncio
async def test_rafaga_del_panel_con_la_misma_clave_crea_un_solo_turno(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    # Reintentos del mismo alta: la idempotencia devuelve el mismo turno (201)
    # o, si la primera sigue en curso, 409 IDEMPOTENCY_IN_PROGRESS.
    headers, service, staffs, slot = await _panel(client, app_sessions, "panelidem")
    cuerpo = _alta(service, staffs[0], slot, 1, "panel-idem-misma-clave")

    respuestas = await asyncio.gather(
        *(
            client.post("/appointments/", headers=headers, json=cuerpo)
            for _ in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert set(codigos) <= {201, 409}, codigos
    creados = {r.json()["public_id"] for r in respuestas if r.status_code == 201}
    assert len(creados) == 1, creados
    assert await _activos(owner_engine, staffs[0]) == 1


@pytest.mark.asyncio
async def test_rafaga_del_panel_con_cualquier_profesional_llena_cada_agenda_una_vez(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    headers, service, staffs, slot = await _panel(
        client, app_sessions, "panelauto", profesionales=2
    )

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/appointments/",
                headers=headers,
                json=_alta(service, None, slot, i, f"panel-auto-{i:02d}"),
            )
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(201) == 2, codigos
    assert set(codigos) <= {201, 409}, codigos
    for staff in staffs:
        assert await _activos(owner_engine, staff) == 1
