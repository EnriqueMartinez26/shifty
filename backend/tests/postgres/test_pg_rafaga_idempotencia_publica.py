"""Rafaga con la MISMA clave de idempotencia sobre los handlers publicos.

Auditoria 2, AUD2-B1-07 (2026-09-20). En SQLite la peticion "en vuelo" se
simula dejando el marcador `PROCESSING` puesto
(`tests/integration/test_idempotencia_libera_solo_la_propia.py`); eso fija el
comportamiento pero no prueba la carrera. Aca N peticiones concurrentes con la
misma clave corren de verdad, cada una con su sesion contra Postgres.

Lo que se fija (regla 6 y §4 de CLAUDE.md): cero 5xx, un solo turno activo, y
—el invariante que rompia el defecto— la clave queda en Redis CON EL
RESULTADO. Antes, la peticion que agotaba `MAX_WAIT_SECONDS` levantaba
`IdempotencyInProgressException` adentro del `try` y el `except` borraba el
`PROCESSING` de la ganadora: la clave quedaba libre, otra peticion entraba al
alta en paralelo y la unica defensa que quedaba era el unico de
`appointments.idempotency_key` mas la exclusion GiST.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.redis import get_redis
from main import app
from modules.public_api.router import _booking_cache_key
from modules.public_api.schemas import PublicBookingCreate
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))


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
async def test_la_rafaga_con_la_misma_clave_deja_el_resultado_en_redis(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, token = await register_and_login(
        client, app_sessions, slug="pg-idem-release", email="pg-idem-release@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(
        client, token, service, email="pro-pg-idem-release@demo.com"
    )
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)
    cuerpo: dict[str, Any] = {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": "Cliente Rafaga",
        "client_phone": "+5491155551234",
        "accepts_terms": True,
        "idempotency_key": "pg-idem-release-0001",
    }

    respuestas = await asyncio.gather(
        *(client.post("/public/appointments", json=cuerpo) for _ in range(RAFAGA))
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert set(codigos) <= {201, 409}, codigos
    creados = {r.json()["public_id"] for r in respuestas if r.status_code == 201}
    assert len(creados) == 1, creados
    assert await _turnos_activos(owner_engine, staff) == 1

    # La clave NO quedo borrada ni en PROCESSING: guarda el resultado, que es
    # lo que hace que un reintento posterior no vuelva a entrar al alta.
    redis = await app.dependency_overrides[get_redis]()
    clave = "idempotency:" + _booking_cache_key(
        PublicBookingCreate(**cuerpo), str(cuerpo["idempotency_key"])
    )
    guardado = await redis.get(clave)
    assert guardado not in (None, "PROCESSING"), guardado
    assert json.loads(guardado)["public_id"] == creados.pop()
