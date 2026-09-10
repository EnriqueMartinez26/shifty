"""Row-Level Security: el aislamiento entre tiendas lo garantiza Postgres.

Con el rol de la aplicacion (``shifty_app``, sin BYPASSRLS) y la RLS forzada,
una consulta sin filtro ``WHERE store_id`` solo devuelve las filas de la
tienda del contexto. Sin contexto no devuelve nada; con contexto de
superadmin devuelve todo. Es la red que queda si un repositorio olvida el
filtro o alguien ejecuta SQL con las credenciales de la app.
"""

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
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres


async def _tienda_con_turno(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str, str]:
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    alta = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": service,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=15, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": f"pg-rls-{slug}",
        },
    )
    assert alta.status_code == 201, alta.text
    return store, token, str(alta.json()["public_id"])


async def _contar_turnos(
    app_engine: AsyncEngine, *, store_id: str | None, global_admin: bool = False
) -> int:
    """SELECT sin WHERE store_id, como shifty_app, bajo el contexto dado."""
    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text(
                    "select set_config('app.current_store_id', :sid, true), "
                    "set_config('app.is_global_admin', :admin, true)"
                ),
                {"sid": store_id or "0", "admin": "true" if global_admin else "false"},
            )
            total = (
                await conn.execute(text("select count(*) from appointments"))
            ).scalar_one()
            return cast(int, total)


@pytest.mark.asyncio
async def test_cada_tienda_ve_solo_sus_filas_sin_filtro_en_la_query(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
) -> None:
    tienda_a, _, _ = await _tienda_con_turno(client, app_sessions, "rls-a")
    tienda_b, _, _ = await _tienda_con_turno(client, app_sessions, "rls-b")

    assert await _contar_turnos(app_engine, store_id=tienda_a) == 1
    assert await _contar_turnos(app_engine, store_id=tienda_b) == 1
    assert await _contar_turnos(app_engine, store_id=None) == 0, (
        "sin contexto RLS filtra todo"
    )
    assert await _contar_turnos(app_engine, store_id=None, global_admin=True) == 2


@pytest.mark.asyncio
async def test_un_update_sin_filtro_no_alcanza_a_la_otra_tienda(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
) -> None:
    tienda_a, _, _ = await _tienda_con_turno(client, app_sessions, "upd-a")
    _, _, turno_b = await _tienda_con_turno(client, app_sessions, "upd-b")

    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text(
                    "select set_config('app.current_store_id', :sid, true), "
                    "set_config('app.is_global_admin', 'false', true)"
                ),
                {"sid": tienda_a},
            )
            # Un UPDATE "olvidado" sin WHERE store_id: RLS lo recorta a la tienda A.
            afectadas = (
                await conn.execute(text("update appointments set notes = 'tocado'"))
            ).rowcount
    assert afectadas == 1

    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text(
                    "select set_config('app.current_store_id', '0', true), "
                    "set_config('app.is_global_admin', 'true', true)"
                )
            )
            nota_b = (
                await conn.execute(
                    text("select notes from appointments where id = :pid"),
                    {"pid": turno_b},
                )
            ).scalar_one()
    assert nota_b != "tocado"


@pytest.mark.asyncio
async def test_por_la_api_el_turno_de_otra_tienda_no_existe(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    _, token_a, _ = await _tienda_con_turno(client, app_sessions, "api-a")
    _, _, turno_b = await _tienda_con_turno(client, app_sessions, "api-b")

    ajeno = await client.get(f"/appointments/{turno_b}", headers=auth_headers(token_a))
    assert ajeno.status_code == 404, ajeno.text
