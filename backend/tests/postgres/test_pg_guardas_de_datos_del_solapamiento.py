"""Guardas de datos para lo que F1-13 da por cierto (revision de perf/f1c, 2026-09-24).

La cota inferior del solapamiento (F1-13) se apoya en dos supuestos sobre los
datos que hasta ahora solo sostenia el codigo:

1. Ningun turno dura mas de un dia. ``ck_appointments_max_span`` lo exige al
   turno, pero la duracion sale del servicio y el tope del producto
   (``le=480`` en ``services/schemas.py``) vive solo en Pydantic: un servicio
   de mas de 1440 minutos (carga directa, script) hacia fallar cada reserva
   con un 409 que nadie entendia. ``ck_services_duration_max`` lo frena donde
   nace.
2. Un turno o un bloqueo tiene la MISMA tienda que su profesional. Las lecturas
   bajo el lock filtran por la tienda del profesional: una fila con otra
   ``store_id`` quedaba invisible para el choque y habilitaba una doble reserva.

La migracion ``c3d5e7f9a1b4`` cuenta las tres cosas y se detiene con el conteo
(no corrige datos por nadie); ``d4e6f8a0b2c5`` valida el CHECK aparte.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    create_service,
    create_staff,
)
from tests.postgres.conftest import alembic, register_and_login

pytestmark = pytest.mark.postgres

REVISION_DE_LAS_GUARDAS = "c3d5e7f9a1b4"


async def _tienda_con_profesional(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str, str]:
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    return store, service, staff


def _padre_de_las_guardas() -> str:
    show = alembic("show", REVISION_DE_LAS_GUARDAS)
    assert show.returncode == 0, show.stderr
    return next(
        linea.split(":", 1)[1].strip()
        for linea in show.stdout.splitlines()
        if linea.startswith("Parent:")
    )


@pytest.mark.asyncio
async def test_la_base_rechaza_un_servicio_de_mas_de_un_dia(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    _store, service, _staff = await _tienda_con_profesional(
        client, app_sessions, "pg-servicio-largo"
    )
    async with owner_engine.connect() as conn:
        validada = (
            await conn.execute(
                text(
                    "select convalidated from pg_constraint "
                    "where conname = 'ck_services_duration_max'"
                )
            )
        ).scalar_one()
    assert validada is True

    with pytest.raises(IntegrityError, match="ck_services_duration_max"):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "update services set duration_minutes = 1441 where public_id = :p"
                ),
                {"p": service},
            )


async def _servicio_largo(owner_engine: AsyncEngine, ids: dict[str, str]) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("update services set duration_minutes = 1441 where public_id = :p"),
            {"p": ids["service"]},
        )


async def _bloqueo_de_otra_tienda(
    owner_engine: AsyncEngine, ids: dict[str, str]
) -> None:
    ahora = datetime.now(timezone.utc)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "insert into appointment_blocks (id, store_id, staff_id, start_time, "
                "end_time, reason, is_active, created_at, updated_at) values "
                "('BLOQUEO-AJENO', :otra, :staff, :ini, :fin, 'x', true, now(), now())"
            ),
            {
                "otra": ids["otra"],
                "staff": ids["staff"],
                "ini": ahora,
                "fin": ahora + timedelta(hours=1),
            },
        )


async def _turno_de_otra_tienda(owner_engine: AsyncEngine, ids: dict[str, str]) -> None:
    async with owner_engine.begin() as conn:
        service_id = (
            await conn.execute(
                text("select id from services where public_id = :p"),
                {"p": ids["service"]},
            )
        ).scalar_one()
        await conn.execute(
            text(
                "insert into appointments (id, store_id, staff_id, service_id, "
                "client_name, starts_at, duration_minutes, status, version, "
                "created_at, updated_at) values ('TURNO-AJENO', :otra, :staff, "
                ":service, 'x', now(), 30, 'confirmed', 1, now(), now())"
            ),
            {"otra": ids["otra"], "staff": ids["staff"], "service": service_id},
        )


Sembrado = Callable[[AsyncEngine, dict[str, str]], Awaitable[None]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sembrar", "mensaje"),
    [
        (_servicio_largo, "1 servicio(s) de mas de 1440 minutos"),
        (_bloqueo_de_otra_tienda, "1 bloqueo(s) con otra tienda que su profesional"),
        (_turno_de_otra_tienda, "1 turno(s) con otra tienda que su profesional"),
    ],
)
async def test_la_migracion_se_detiene_con_el_conteo(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    sembrar: Sembrado,
    mensaje: str,
) -> None:
    store, service, staff = await _tienda_con_profesional(
        client, app_sessions, "pg-guardas"
    )
    otra, _ = await register_and_login(
        client, app_sessions, slug="pg-guardas-otra", email="pg-guardas-otra@demo.com"
    )
    ids = {"store": store, "service": service, "staff": staff, "otra": otra}

    abajo = alembic("downgrade", _padre_de_las_guardas())
    assert abajo.returncode == 0, abajo.stderr[-2000:]
    try:
        await sembrar(owner_engine, ids)
        arriba = alembic("upgrade", "head")
        assert arriba.returncode != 0
        assert mensaje in arriba.stderr, arriba.stderr[-2000:]
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("delete from appointment_blocks where id = 'BLOQUEO-AJENO'")
            )
            await conn.execute(
                text("delete from appointments where id = 'TURNO-AJENO'")
            )
            await conn.execute(
                text("update services set duration_minutes = 30 where public_id = :p"),
                {"p": service},
            )
        final = alembic("upgrade", "head")
        assert final.returncode == 0, final.stderr[-2000:]
