"""Varios servicios en un turno contra Postgres (decision de Mateo, 2026-10-16).

Lo que SQLite no prueba (CLAUDE.md §4):

- Rafagas: N reservas identicas de Corte + Barba (misma clave) dejan UN turno,
  y N sobre el mismo horario dan 1 exito, N-1 conflictos y cero 5xx.
- La exclusion GiST cubre el rango ENTERO del turno largo: un turno que solo
  pisa la cola (la parte de la Barba) lo rechaza la base aunque el codigo
  fallara.
- RLS: con el rol de la app y sin ``WHERE store_id``, una tienda no ve los
  turnos de varios servicios de otra.
- ``ck_appointments_extra_services_amount`` (validado por ``c9e1a3b5d7f2``).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

import pytest
import ulid
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))
DURACION = timedelta(minutes=50)


async def _servicio(client: AsyncClient, token: str, nombre: str, minutos: int) -> str:
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": nombre, "duration_minutes": minutos, "price": 1000 * minutos},
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


async def _tienda(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str, str, str, datetime]:
    """Tienda con el flag prendido, Corte (30 min) y Barba (20 min) sin sena y
    un profesional que hace los dos."""
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    flag = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"multi_service_booking": True},
    )
    assert flag.status_code == 200, flag.text
    corte = await _servicio(client, token, "Corte", 30)
    barba = await _servicio(client, token, "Barba", 20)
    alta = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": "Ana",
            "first_name": "Ana",
            "last_name": "Demo",
            "email": f"ana-{slug}@demo.com",
            "service_ids": [corte, barba],
        },
    )
    assert alta.status_code == 201, alta.text
    staff = cast(str, alta.json()["public_id"])
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)
    return store, corte, barba, staff, slot


def _reserva(
    store: str, corte: str, barba: str, staff: str, slot: datetime, i: int
) -> dict[str, Any]:
    return {
        "store_public_id": store,
        "service_id": corte,
        "extra_service_ids": [barba],
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": f"Cliente {i}",
        "client_phone": f"+54911577{i:05d}",
        "client_email": f"c54911577{i:05d}@example.com",
        "accepts_terms": True,
        "idempotency_key": f"pg-varios-{i:06d}",
    }


async def _activos(owner_engine: AsyncEngine, staff: str) -> list[Any]:
    async with owner_engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    text(
                        "select starts_at, ends_at, duration_minutes, "
                        "extra_services_amount, extra_services_snapshot "
                        "from appointments where staff_id = :staff "
                        "and status in ('pending','pending_payment','confirmed')"
                    ),
                    {"staff": staff},
                )
            ).all()
        )


def _congelado_ok(fila: Any, barba: str) -> None:
    inicio, fin, minutos, extras, snapshot = fila
    assert fin - inicio == DURACION
    assert minutos == 50
    assert extras == Decimal("20000.00")
    assert [(x["public_id"], x["duration_minutes"]) for x in snapshot] == [(barba, 20)]


# ---------------------------------------------------------------------------
# Rafagas
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rafaga_identica_de_varios_servicios_deja_un_turno(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, corte, barba, staff, slot = await _tienda(
        client, app_sessions, "pg-varios-identica"
    )
    cuerpo = _reserva(store, corte, barba, staff, slot, 1)

    respuestas = await asyncio.gather(
        *(client.post("/public/appointments", json=cuerpo) for _ in range(RAFAGA))
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), [
        r.text for r in respuestas if r.status_code >= 500
    ]
    assert set(codigos) <= {201, 409}, codigos
    creados = {r.json()["public_id"] for r in respuestas if r.status_code == 201}
    assert len(creados) == 1, creados
    (fila,) = await _activos(owner_engine, staff)
    _congelado_ok(fila, barba)


@pytest.mark.asyncio
async def test_rafaga_de_varios_servicios_sobre_el_mismo_horario(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, corte, barba, staff, slot = await _tienda(
        client, app_sessions, "pg-varios-slot"
    )

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/public/appointments",
                json=_reserva(store, corte, barba, staff, slot, i),
            )
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), [
        r.text for r in respuestas if r.status_code >= 500
    ]
    assert codigos.count(201) == 1, codigos
    assert codigos.count(409) == RAFAGA - 1, codigos
    (fila,) = await _activos(owner_engine, staff)
    _congelado_ok(fila, barba)


@pytest.mark.asyncio
async def test_rafaga_que_pisa_solo_la_cola_del_turno_largo(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """La mitad de la rafaga pide Corte + Barba a las 11:00 (hasta las 11:50) y
    la otra mitad un Corte solo a las 11:30: se pisan en la cola. Un solo
    turno queda y no hay 5xx."""
    store, corte, barba, staff, slot = await _tienda(
        client, app_sessions, "pg-varios-cola"
    )

    def cuerpo(i: int) -> dict[str, Any]:
        if i % 2 == 0:
            return _reserva(store, corte, barba, staff, slot, i)
        return _reserva(store, corte, barba, staff, slot, i) | {
            "extra_service_ids": [],
            "starts_at": (slot + timedelta(minutes=30)).isoformat(),
        }

    respuestas = await asyncio.gather(
        *(client.post("/public/appointments", json=cuerpo(i)) for i in range(RAFAGA))
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), [
        r.text for r in respuestas if r.status_code >= 500
    ]
    assert codigos.count(201) == 1, codigos
    assert len(await _activos(owner_engine, staff)) == 1


# ---------------------------------------------------------------------------
# GiST, RLS y CHECK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_exclusion_gist_cubre_el_rango_entero_del_turno_largo(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """Un turno escrito a mano (sin pasar por el codigo) que empieza a las
    11:40, dentro de la Barba, lo rechaza la exclusion GiST."""
    store, corte, barba, staff, slot = await _tienda(
        client, app_sessions, "pg-varios-gist"
    )
    alta = await client.post(
        "/public/appointments", json=_reserva(store, corte, barba, staff, slot, 1)
    )
    assert alta.status_code == 201, alta.text
    turno = alta.json()["public_id"]

    with pytest.raises(IntegrityError, match="ex_appointments_no_active_overlap"):
        await _turno_a_mano(owner_engine, turno, desde_minuto=40)
    # Desde el fin del turno largo (11:50) el horario esta libre: el rango que
    # guarda la base es exactamente [11:00, 11:50).
    await _turno_a_mano(owner_engine, turno, desde_minuto=50)


async def _turno_a_mano(
    owner_engine: AsyncEngine, turno: str, *, desde_minuto: int
) -> None:
    """Un Corte de 30 minutos del mismo profesional, ``desde_minuto`` despues
    del inicio del turno ``turno``, insertado saltando la aplicacion."""
    async with owner_engine.begin() as conn:
        columnas = [
            r[0]
            for r in (
                await conn.execute(
                    text(
                        "select column_name from information_schema.columns "
                        "where table_schema='public' and table_name='appointments' "
                        "order by ordinal_position"
                    )
                )
            ).all()
        ]
        reemplazos = {
            "id": ":nuevo",
            "idempotency_key": "NULL",
            "starts_at": f"starts_at + interval '{desde_minuto} minutes'",
            "ends_at": f"starts_at + interval '{desde_minuto + 30} minutes'",
            "duration_minutes": "30",
            "extra_services_amount": "0",
            "extra_services_snapshot": "NULL",
            "status": "'pending'",
        }
        seleccion = ", ".join(reemplazos.get(c, c) for c in columnas)
        await conn.execute(
            text(
                f"insert into appointments ({', '.join(columnas)}) "
                f"select {seleccion} from appointments where id = :pid"
            ),
            {"nuevo": str(ulid.ULID()), "pid": turno},
        )


async def _contar_con_extras(app_engine: AsyncEngine, *, store_id: str) -> int:
    """SELECT sin WHERE store_id, como shifty_app, bajo el contexto dado."""
    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text(
                    "select set_config('app.current_store_id', :sid, true), "
                    "set_config('app.is_global_admin', 'false', true)"
                ),
                {"sid": store_id},
            )
            total = (
                await conn.execute(
                    text(
                        "select count(*) from appointments "
                        "where extra_services_snapshot is not null"
                    )
                )
            ).scalar_one()
            return cast(int, total)


@pytest.mark.asyncio
async def test_una_tienda_no_ve_los_turnos_de_varios_servicios_de_otra(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
) -> None:
    tienda_a, corte, barba, staff, slot = await _tienda(
        client, app_sessions, "pg-varios-rls-a"
    )
    tienda_b, *_ = await _tienda(client, app_sessions, "pg-varios-rls-b")
    alta = await client.post(
        "/public/appointments", json=_reserva(tienda_a, corte, barba, staff, slot, 1)
    )
    assert alta.status_code == 201, alta.text

    assert await _contar_con_extras(app_engine, store_id=tienda_a) == 1
    assert await _contar_con_extras(app_engine, store_id=tienda_b) == 0


@pytest.mark.asyncio
async def test_la_base_rechaza_un_importe_de_extras_negativo(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, corte, barba, staff, slot = await _tienda(
        client, app_sessions, "pg-varios-check"
    )
    alta = await client.post(
        "/public/appointments", json=_reserva(store, corte, barba, staff, slot, 1)
    )
    assert alta.status_code == 201, alta.text

    with pytest.raises(IntegrityError, match="ck_appointments_extra_services_amount"):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "update appointments set extra_services_amount = -1 where id = :id"
                ),
                {"id": alta.json()["public_id"]},
            )
    async with owner_engine.connect() as conn:
        validada = (
            await conn.execute(
                text(
                    "select convalidated from pg_constraint "
                    "where conname = 'ck_appointments_extra_services_amount'"
                )
            )
        ).scalar_one()
    # La revision B (c9e1a3b5d7f2) la valido.
    assert validada is True
