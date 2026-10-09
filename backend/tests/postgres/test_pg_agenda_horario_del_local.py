"""Horario del local como respaldo y duenio del turno, contra Postgres real.

2026-09-29 (D-20260929-01/02/03 en docs/DECISIONES.md). Lo que SQLite no
prueba de ese cambio:

- ``working_hours.load_effective_hours`` lee ``staff`` + ``schedules`` con un
  ``EXISTS`` correlacionado y, para el respaldo, ``store_schedules``: bajo RLS
  y como ``shifty_app``, tanto en el portal publico como en el panel.
- La rafaga sobre un profesional SIN franjas (jornada = horario del local):
  1 exito, N-1 conflictos, cero 5xx (CLAUDE.md §4). La validacion del horario
  va antes del lock y no cambia el camino del lock (regla 4).
- La reprogramacion en rafaga por el profesional DUENIO del turno (el unico
  profesional que puede moverlo desde el panel): una sola gana.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.utils import ARGENTINA_TZ
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login
from tests.postgres.test_pg_cancelar_con_cobro_vivo import _profesional

pytestmark = pytest.mark.postgres

RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))
# Mismo tope que la rafaga de reprogramaciones de test_pg_reserva_concurrente:
# los originales tienen que entrar en la jornada sin pisarse.
RAFAGA_REPROGRAMACION = min(RAFAGA, 10)
DIAS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


async def _tienda_sin_franjas(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str, str, str, datetime]:
    """Tienda con horario comercial 06 a 18 local y un profesional SIN franjas."""
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    # 11:00 UTC = 08:00 local: el mismo dia calendario en los dos husos.
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)
    clave = DIAS[slot.astimezone(ARGENTINA_TZ).weekday()]
    horario = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"business_hours": {clave: [{"open": "06:00", "close": "18:00"}]}},
    )
    assert horario.status_code == 200, horario.text
    return store, token, service, staff, slot


async def _activos_en(owner_engine: AsyncEngine, staff: str, inicio: datetime) -> int:
    async with owner_engine.connect() as conn:
        total = (
            await conn.execute(
                text(
                    "select count(*) from appointments "
                    "where staff_id = :staff and starts_at = :inicio "
                    "and status in ('pending','pending_payment','confirmed')"
                ),
                {"staff": staff, "inicio": inicio},
            )
        ).scalar_one()
        return cast(int, total)


def _reserva(
    store: str, service: str, staff: str, slot: datetime, i: int
) -> dict[str, Any]:
    return {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": f"Cliente {i}",
        "client_phone": f"+54911556{i:05d}",
        "accepts_terms": True,
        "idempotency_key": f"pg-local-{i:04d}",
    }


@pytest.mark.asyncio
async def test_disponibilidad_bajo_rls_usa_el_horario_del_local(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    _store, token, service, staff, slot = await _tienda_sin_franjas(
        client, app_sessions, "pg-local-dispo"
    )
    fecha = slot.astimezone(ARGENTINA_TZ).date().isoformat()

    panel = await client.get(
        "/appointments/availability",
        headers=auth_headers(token),
        params={"service_id": service, "date": fecha},
    )
    anonima = await client.get(
        "/appointments/availability", params={"service_id": service, "date": fecha}
    )

    for res in (panel, anonima):
        assert res.status_code == 200, res.text
        horas = [s["start_time"] for s in res.json() if s["staff_id"] == staff]
        assert horas and min(horas) == "06:00:00", res.text


@pytest.mark.asyncio
async def test_rafaga_publica_sobre_el_horario_del_local_deja_pasar_una(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, _token, service, staff, slot = await _tienda_sin_franjas(
        client, app_sessions, "pg-local-rafaga"
    )

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/public/appointments", json=_reserva(store, service, staff, slot, i)
            )
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(201) == 1, codigos
    assert set(codigos) <= {201, 409}, codigos
    assert await _activos_en(owner_engine, staff, slot) == 1


@pytest.mark.asyncio
async def test_rafaga_de_reprogramaciones_del_profesional_duenio(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """N turnos del MISMO profesional (sin franjas) movidos a la vez al mismo
    horario por el propio profesional: uno gana, el resto 409, cero 5xx."""
    slug = "pg-local-repro"
    store, token, service, staff, slot = await _tienda_sin_franjas(
        client, app_sessions, slug
    )
    turnos: list[str] = []
    # Originales cada 30 minutos desde las 06:00 local (09:00 UTC).
    for i in range(RAFAGA_REPROGRAMACION):
        inicio = slot.replace(hour=9) + timedelta(minutes=30 * i)
        res = await client.post(
            "/public/appointments", json=_reserva(store, service, staff, inicio, i)
        )
        assert res.status_code == 201, res.text
        turnos.append(str(res.json()["public_id"]))
    profesional = await _profesional(client, token, f"pro-{slug}@demo.com")
    # 20:00 UTC = 17:00 local: dentro del horario del local y libre.
    destino = slot.replace(hour=20)

    respuestas = await asyncio.gather(
        *(
            client.patch(
                f"/appointments/{turno}/reschedule",
                headers=auth_headers(profesional),
                json={
                    "new_starts_at": destino.isoformat(),
                    "idempotency_key": f"pg-local-repro-{i:04d}",
                },
            )
            for i, turno in enumerate(turnos)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(200) == 1, codigos
    assert set(codigos) <= {200, 409}, codigos
    assert await _activos_en(owner_engine, staff, destino) == 1
