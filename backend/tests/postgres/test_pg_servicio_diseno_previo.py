"""Diseno previo del servicio contra el esquema MIGRADO (2026-10-21, S7).

La suite de SQLite crea las tablas desde el modelo (``create_all``); esta
prueba mira lo que deja la migracion ``a7c9e1b3d5f7``:

- ``requires_prior_design`` es NOT NULL con default ``false`` en la base: un
  INSERT del codigo anterior (sin la columna) nace sin diseno previo.
- ``prior_design_message`` es ``varchar(500)`` nullable, el mismo tope que el
  schema.
- El panel la escribe y el portal la lee con el rol de la app (RLS).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import ulid
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.database import _apply_tenant_context, set_tenant_context
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

MENSAJE = "Mandanos por WhatsApp una foto del diseño."


@pytest.mark.asyncio
async def test_las_columnas_quedan_como_las_declara_el_modelo(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.connect() as conn:
        filas = (
            await conn.execute(
                text(
                    "select column_name, data_type, is_nullable, column_default, "
                    "character_maximum_length from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'services' "
                    "and column_name in "
                    "('requires_prior_design', 'prior_design_message')"
                )
            )
        ).all()
    columnas = {fila[0]: fila[1:] for fila in filas}
    assert columnas["requires_prior_design"] == ("boolean", "NO", "false", None)
    assert columnas["prior_design_message"] == (
        "character varying",
        "YES",
        None,
        500,
    )


@pytest.mark.asyncio
async def test_un_insert_sin_las_columnas_nace_sin_diseno_previo(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    store_public_id, _ = await register_and_login(
        client, app_sessions, slug="pg-dp-legado", email="pg-dp-legado@demo.com"
    )
    ahora = datetime.now(timezone.utc)
    async with app_sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            await session.execute(
                text(
                    "insert into services (id, public_id, store_id, name, "
                    "duration_minutes, price, deposit_mode, deposit_type, "
                    "is_active, created_at, updated_at) values (:id, :public_id, "
                    ":store_id, 'Legado', 30, 1500, 'none', 'percent', true, "
                    ":ahora, :ahora)"
                ),
                {
                    "id": str(ulid.ULID()),
                    "public_id": str(ulid.ULID()),
                    "store_id": store_public_id,
                    "ahora": ahora,
                },
            )
            fila = (
                await session.execute(
                    text(
                        "select requires_prior_design, prior_design_message "
                        "from services where store_id = :store_id"
                    ),
                    {"store_id": store_public_id},
                )
            ).one()
            await session.commit()
        finally:
            set_tenant_context(None, False)
    assert tuple(fila) == (False, None)


@pytest.mark.asyncio
async def test_el_panel_lo_escribe_y_el_portal_lo_lee(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    store_public_id, token = await register_and_login(
        client, app_sessions, slug="pg-dp-portal", email="pg-dp-portal@demo.com"
    )
    alta = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={
            "name": "Unas esculpidas",
            "duration_minutes": 90,
            "price": 20000,
            "requires_prior_design": True,
            "prior_design_message": MENSAJE,
        },
    )
    assert alta.status_code == 201, alta.text
    servicio = alta.json()["public_id"]
    staff = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": "Natalia",
            "first_name": "Natalia",
            "last_name": "Demo",
            "email": "pg-dp-portal-pro@demo.com",
            "service_ids": [servicio],
        },
    )
    assert staff.status_code == 201, staff.text

    publico = await client.get(
        "/public/services", params={"store_public_id": store_public_id}
    )

    assert publico.status_code == 200, publico.text
    (leido,) = publico.json()
    assert leido["requires_prior_design"] is True
    assert leido["prior_design_message"] == MENSAJE
