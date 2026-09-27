"""Reprogramar y bloquear a la vez en orden cruzado: nunca un 5xx (S-18).

Reprogramar lockea el turno original y despues al profesional; el alta de
bloqueos lockea al profesional y despues los turnos del rango. Si el turno
que se reprograma cae dentro del rango que se esta bloqueando, las dos
transacciones pueden esperarse en ciclo y Postgres aborta una (40P01). El
handler de ``main.py`` la responde como 409 neutro. Este test lanza muchas
veces el cruce y exige que ninguna respuesta sea 5xx. En SQLite no hay locks
de fila: solo se prueba contra Postgres.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

INTENTOS = 8


@pytest.mark.asyncio
async def test_reprogramar_y_bloquear_en_orden_cruzado_no_da_5xx(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    _store, token = await register_and_login(
        client, app_sessions, slug="cruce-locks", email="cruce-locks@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-cruce@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    base = dia.replace(hour=9, minute=0, second=0, microsecond=0)

    codigos: list[int] = []
    for i in range(INTENTOS):
        inicio = base + timedelta(minutes=30 * i)
        turno = await client.post(
            "/appointments/",
            headers=auth_headers(token),
            json={
                "service_id": service,
                "staff_id": staff,
                "starts_at": inicio.isoformat(),
                "idempotency_key": f"cruce-locks-turno-{i:03d}",
            },
        )
        assert turno.status_code == 201, turno.text
        # Reprogramar el turno a otro horario mientras se bloquea un rango
        # que lo contiene (con cancelacion en bloque): turno <-> profesional.
        reprogramacion, bloqueo = await asyncio.gather(
            client.patch(
                f"/appointments/{turno.json()['public_id']}/reschedule",
                headers=auth_headers(token),
                json={
                    "new_starts_at": (inicio + timedelta(hours=6)).isoformat(),
                    "idempotency_key": f"cruce-locks-repro-{i:03d}",
                },
            ),
            client.post(
                "/appointment-blocks/",
                headers=auth_headers(token),
                json={
                    "staff_id": staff,
                    "starts_at": inicio.isoformat(),
                    "ends_at": (inicio + timedelta(minutes=30)).isoformat(),
                    "reason": "Cruce",
                    "cancel_affected": True,
                },
            ),
        )
        codigos += [reprogramacion.status_code, bloqueo.status_code]
        for res in (reprogramacion, bloqueo):
            if res.status_code == 409:
                assert res.json()["error_code"] in {
                    "CONCURRENT_MODIFICATION",
                    "APPOINTMENT_CONFLICT",
                    "SCHEDULE_BLOCKED",
                    "BLOCK_HAS_APPOINTMENTS",
                    "RESOURCE_CONFLICT",
                    "INVALID_STATUS_TRANSITION",
                }, res.text

    assert all(c < 500 for c in codigos), codigos
