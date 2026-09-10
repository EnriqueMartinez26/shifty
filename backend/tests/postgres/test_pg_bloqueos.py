"""Carrera bloqueo contra reserva, en Postgres real (Fase 1).

Antes ``book`` leia los bloqueos antes de tomar el lock del profesional y el
alta de bloqueos no tomaba lock alguno: una reserva podia colarse dentro de
un bloqueo recien creado. Ahora ambos toman ``FOR UPDATE`` sobre el
profesional, asi que a lo sumo uno de los dos gana.
"""

import asyncio
from datetime import datetime, timedelta, timezone

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


@pytest.mark.asyncio
async def test_reserva_y_bloqueo_concurrentes_no_dejan_un_turno_adentro(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, token = await register_and_login(
        client, app_sessions, slug="carrera-bloqueo", email="carrera-bloqueo@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-carrera@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)

    for intento in range(5):
        reserva, bloqueo = await asyncio.gather(
            client.post(
                "/public/appointments",
                json={
                    "store_public_id": store,
                    "service_id": service,
                    "staff_id": staff,
                    "starts_at": (slot + timedelta(hours=intento)).isoformat(),
                    "client_name": "Carrera",
                    "client_phone": f"+54911555{intento:05d}",
                    "idempotency_key": f"pg-carrera-{intento:03d}",
                },
            ),
            client.post(
                "/appointment-blocks/",
                headers=auth_headers(token),
                json={
                    "staff_id": staff,
                    "starts_at": (slot + timedelta(hours=intento)).isoformat(),
                    "ends_at": (
                        slot + timedelta(hours=intento, minutes=45)
                    ).isoformat(),
                    "reason": "Carrera",
                },
            ),
        )
        assert reserva.status_code < 500 and bloqueo.status_code < 500, (
            reserva.text,
            bloqueo.text,
        )
        assert not (reserva.status_code == 201 and bloqueo.status_code == 201), (
            "reserva y bloqueo ganaron a la vez",
            reserva.text,
            bloqueo.text,
        )

    # Invariante final: ningun turno activo dentro de un bloqueo activo.
    async with owner_engine.connect() as conn:
        huerfanos = (
            await conn.execute(
                text(
                    "select count(*) from appointments a join appointment_blocks b "
                    "on b.staff_id = a.staff_id and b.is_active "
                    "and b.start_time < a.ends_at and b.end_time > a.starts_at "
                    "where a.status in ('pending','pending_payment','confirmed')"
                )
            )
        ).scalar_one()
    assert huerfanos == 0
