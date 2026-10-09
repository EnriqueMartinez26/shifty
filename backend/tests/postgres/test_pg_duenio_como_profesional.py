"""El dueno que tambien atiende, contra Postgres real (2026-10-08).

Lo que SQLite no prueba de ``POST /staff/me``: la ficha se escribe como
``shifty_app`` bajo RLS con el ``store_id`` de la cuenta, y el portal publico
(``tenant_bypass``) y la grilla la leen. Tambien que quitarse de la agenda no
le desactiva la cuenta: su sesion sigue andando.

Y la rafaga (regla de §4, revision de #133): ``add_self`` era "leer y despues
insertar" sin lock; N pedidos simultaneos veian "sin ficha" y el segundo
``INSERT`` chocaba con la clave primaria (409 generico de ``IntegrityError``,
no ``STAFF_SELF_ALREADY_EXISTS``). Ahora la fila ``users`` de quien llama se
toma con ``FOR UPDATE`` antes de leer.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.utils import ARGENTINA_TZ
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    create_service,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = min(int(os.getenv("TEST_POSTGRES_RAFAGA", "25")), 10)

DIAS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@pytest.mark.asyncio
async def test_el_duenio_agregado_tiene_turnos_bajo_rls_y_conserva_la_cuenta(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, token = await register_and_login(
        client, app_sessions, slug="pg-duenio", email="pg-duenio@demo.com"
    )
    service = await create_service(client, token)
    dia = (datetime.now(timezone.utc) + timedelta(days=5)).astimezone(ARGENTINA_TZ)
    horario = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={
            "business_hours": {
                DIAS[dia.weekday()]: [{"open": "09:00", "close": "18:00"}]
            }
        },
    )
    assert horario.status_code == 200, horario.text

    alta = await client.post(
        "/staff/me", headers=auth_headers(token), json={"service_ids": [service]}
    )

    assert alta.status_code == 201, alta.text
    yo = alta.json()["public_id"]
    async with owner_engine.connect() as conn:
        fila = (
            await conn.execute(
                text(
                    "select s.store_id = u.store_id as misma_tienda, u.role, "
                    "(select count(*) from users where email = u.email) as cuentas "
                    "from staff s join users u on u.id = s.id where s.id = :yo"
                ),
                {"yo": yo},
            )
        ).one()
    assert fila.misma_tienda is True
    assert fila.role == "admin"
    assert fila.cuentas == 1

    slots = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": dia.date().isoformat(),
        },
    )
    assert slots.status_code == 200, slots.text
    assert any(s["staff_id"] == yo for s in slots.json()), slots.text

    baja = await client.delete(f"/staff/{yo}", headers=auth_headers(token))
    assert baja.status_code == 204, baja.text
    sigue = await client.get("/staff/", headers=auth_headers(token))
    assert sigue.status_code == 200, sigue.text


@pytest.mark.asyncio
async def test_rafaga_de_agregarme_deja_una_sola_ficha(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    _store, token = await register_and_login(
        client, app_sessions, slug="pg-duenio-rafaga", email="pg-duenio-rafaga@demo.com"
    )

    respuestas = await asyncio.gather(
        *(
            client.post("/staff/me", headers=auth_headers(token), json={})
            for _ in range(RAFAGA)
        )
    )

    codigos = sorted(r.status_code for r in respuestas)
    assert codigos == [201] + [409] * (RAFAGA - 1), [r.text for r in respuestas]
    assert all(
        r.json()["error_code"] == "STAFF_SELF_ALREADY_EXISTS"
        for r in respuestas
        if r.status_code == 409
    ), [r.text for r in respuestas]
    async with owner_engine.connect() as conn:
        fichas = (
            await conn.execute(
                text(
                    "select count(*) from staff s join users u on u.id = s.id "
                    "where u.email = :email"
                ),
                {"email": "pg-duenio-rafaga@demo.com"},
            )
        ).scalar_one()
    assert fichas == 1
