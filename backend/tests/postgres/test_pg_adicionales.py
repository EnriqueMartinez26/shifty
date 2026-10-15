"""Adicionales contra Postgres (decision de Mateo, 2026-10-14).

Lo que SQLite no prueba (CLAUDE.md §4):

- RLS forzada sobre ``service_addons``: con el rol de la app y sin
  ``WHERE store_id``, cada tienda ve solo sus adicionales.
- Los CHECK de ``service_addons`` y ``ck_appointments_addons_amount`` (el
  total congelado nunca es menor que su parte de adicionales).
- Rafaga con adicionales: N reservas identicas (misma clave) dejan un turno,
  y N sobre el mismo horario dan 1 exito, N-1 conflictos y cero 5xx. El turno
  que queda congela el total y los adicionales.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))


async def _tienda(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str, str, str, datetime]:
    """Tienda con un servicio de $27.000 sin sena y un adicional de $500."""
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={
            "name": "Unas",
            "duration_minutes": 60,
            "price": 27000,
            "addons": [{"name": "Strass", "unit_price": 500, "max_quantity": 10}],
        },
    )
    assert res.status_code == 201, res.text
    servicio = cast(str, res.json()["public_id"])
    adicional = cast(str, res.json()["addons"][0]["id"])
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)
    return store, servicio, staff, adicional, slot


def _reserva(
    store: str, servicio: str, staff: str, adicional: str, slot: datetime, i: int
) -> dict[str, Any]:
    return {
        "store_public_id": store,
        "service_id": servicio,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": f"Cliente {i}",
        "client_phone": f"+54911566{i:05d}",
        "client_email": f"c54911566{i:05d}@example.com",
        "accepts_terms": True,
        "idempotency_key": f"pg-adic-{i:06d}",
        "addons": [{"addon_id": adicional, "quantity": 6}],
    }


async def _activos(owner_engine: AsyncEngine, staff: str) -> list[Any]:
    async with owner_engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    text(
                        "select price_amount, addons_amount, addons_snapshot "
                        "from appointments where staff_id = :staff "
                        "and status in ('pending','pending_payment','confirmed')"
                    ),
                    {"staff": staff},
                )
            ).all()
        )


def _congelado_ok(fila: Any) -> None:
    precio, adicionales, snapshot = fila
    assert precio == Decimal("30000.00")
    assert adicionales == Decimal("3000.00")
    assert [(x["name"], x["quantity"], x["amount"]) for x in snapshot] == [
        ("Strass", 6, "3000.00")
    ]


# ---------------------------------------------------------------------------
# Rafagas
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rafaga_identica_con_adicionales_deja_un_turno(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, servicio, staff, adicional, slot = await _tienda(
        client, app_sessions, "pg-adic-identica"
    )
    cuerpo = _reserva(store, servicio, staff, adicional, slot, 1)

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
    _congelado_ok(fila)


@pytest.mark.asyncio
async def test_rafaga_sobre_el_mismo_horario_con_adicionales(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, servicio, staff, adicional, slot = await _tienda(
        client, app_sessions, "pg-adic-slot"
    )

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/public/appointments",
                json=_reserva(store, servicio, staff, adicional, slot, i),
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
    _congelado_ok(fila)


@pytest.mark.asyncio
async def test_rafaga_de_ediciones_conserva_los_ids_y_no_suma_conjuntos(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """Revision de la PR #187: N PATCH a la vez con la lista entera (lo que
    manda el panel) se serializan en el lock del servicio. Con el mismo
    precio los ids se conservan, el conjunto final es el pedido (sin union de
    dos reemplazos) y no hay 5xx."""
    _store, token = await register_and_login(
        client, app_sessions, slug="pg-adic-upsert", email="pg-adic-upsert@demo.com"
    )
    creado = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={
            "name": "Unas",
            "duration_minutes": 60,
            "price": 27000,
            "addons": [
                {"name": "Strass", "unit_price": 500, "max_quantity": 10},
                {"name": "Diseno", "unit_price": 1500},
            ],
        },
    )
    assert creado.status_code == 201, creado.text
    servicio = creado.json()["public_id"]
    ids = [a["id"] for a in creado.json()["addons"]]
    formulario = [
        {k: a[k] for k in ("id", "name", "unit_price", "max_quantity")}
        for a in creado.json()["addons"]
    ]

    respuestas = await asyncio.gather(
        *(
            client.patch(
                f"/services/{servicio}",
                headers=auth_headers(token),
                json={"description": f"Edicion {i}", "addons": formulario},
            )
            for i in range(RAFAGA)
        )
    )

    codigos = sorted(r.status_code for r in respuestas)
    assert all(c < 500 for c in codigos), [
        r.text for r in respuestas if r.status_code >= 500
    ]
    assert codigos.count(200) >= 1, codigos
    async with owner_engine.connect() as conn:
        filas = (
            await conn.execute(
                text(
                    "select a.id from service_addons a join services s "
                    "on s.id = a.service_id where s.public_id = :p order by a.position"
                ),
                {"p": servicio},
            )
        ).all()
    assert [f[0] for f in filas] == ids


# ---------------------------------------------------------------------------
# RLS
# ---------------------------------------------------------------------------


async def _contar_adicionales(
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
                await conn.execute(text("select count(*) from service_addons"))
            ).scalar_one()
            return cast(int, total)


@pytest.mark.asyncio
async def test_cada_tienda_ve_solo_sus_adicionales_sin_filtro_en_la_query(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
) -> None:
    tienda_a, *_ = await _tienda(client, app_sessions, "pg-adic-rls-a")
    tienda_b, *_ = await _tienda(client, app_sessions, "pg-adic-rls-b")
    async with owner_engine.connect() as conn:
        forzada = (
            await conn.execute(
                text(
                    "select relrowsecurity, relforcerowsecurity from pg_class "
                    "where relname = 'service_addons'"
                )
            )
        ).one()
    assert tuple(forzada) == (True, True)

    assert await _contar_adicionales(app_engine, store_id=tienda_a) == 1
    assert await _contar_adicionales(app_engine, store_id=tienda_b) == 1
    assert await _contar_adicionales(app_engine, store_id=None) == 0
    assert await _contar_adicionales(app_engine, store_id=None, global_admin=True) == 2


@pytest.mark.asyncio
async def test_la_app_no_escribe_un_adicional_en_otra_tienda(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
) -> None:
    tienda_a, *_ = await _tienda(client, app_sessions, "pg-adic-escribe-a")
    tienda_b, *_ = await _tienda(client, app_sessions, "pg-adic-escribe-b")
    async with owner_engine.connect() as conn:
        servicio_b = (
            await conn.execute(
                text("select id from services where store_id = :s"), {"s": tienda_b}
            )
        ).scalar_one()

    with pytest.raises(Exception, match="row-level security"):
        async with app_engine.connect() as conn:
            async with conn.begin():
                await conn.execute(
                    text("select set_config('app.current_store_id', :sid, true)"),
                    {"sid": tienda_a},
                )
                await conn.execute(
                    text(
                        "insert into service_addons (id, created_at, updated_at, "
                        "store_id, service_id, name, unit_price, max_quantity, "
                        "position) values ('adic-intruso', now(), now(), :b, "
                        ":svc, 'Intruso', 1, 1, 0)"
                    ),
                    {"b": tienda_b, "svc": servicio_b},
                )


# ---------------------------------------------------------------------------
# CHECKs
# ---------------------------------------------------------------------------

_INSERT_ADICIONAL = (
    "insert into service_addons (id, created_at, updated_at, store_id, "
    "service_id, name, unit_price, max_quantity, position) values "
    "(:id, now(), now(), :store, :svc, :name, :price, :max, :pos)"
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("campos", "restriccion"),
    [
        ({"price": Decimal("-1")}, "ck_service_addons_unit_price"),
        ({"price": Decimal("1000000.01")}, "ck_service_addons_unit_price"),
        ({"max": 0}, "ck_service_addons_max_quantity"),
        ({"max": 100}, "ck_service_addons_max_quantity"),
        ({"name": ""}, "ck_service_addons_name"),
        ({"pos": 20}, "ck_service_addons_position"),
        ({"pos": -1}, "ck_service_addons_position"),
    ],
)
async def test_la_base_rechaza_un_adicional_fuera_de_los_topes(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    campos: dict[str, Any],
    restriccion: str,
) -> None:
    store, *_ = await _tienda(client, app_sessions, "pg-adic-check")
    async with owner_engine.connect() as conn:
        servicio = (
            await conn.execute(
                text("select id from services where store_id = :s"), {"s": store}
            )
        ).scalar_one()
    valores = {
        "id": "adic-check",
        "store": store,
        "svc": servicio,
        "name": "Strass",
        "price": Decimal("1"),
        "max": 1,
        "pos": 0,
    } | campos

    with pytest.raises(IntegrityError, match=restriccion):
        async with owner_engine.begin() as conn:
            await conn.execute(text(_INSERT_ADICIONAL), valores)


@pytest.mark.asyncio
async def test_el_turno_no_congela_adicionales_negativos(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """``ck_appointments_addons_amount`` = ``addons_amount >= 0``. Un total
    menor que los adicionales SI vale: la promo se aplica al total (decision
    de Mateo, 2026-10-15) y ``addons_amount`` es la suma sin descuento."""
    store, servicio, staff, adicional, slot = await _tienda(
        client, app_sessions, "pg-adic-check-turno"
    )
    alta = await client.post(
        "/public/appointments",
        json=_reserva(store, servicio, staff, adicional, slot, 1),
    )
    assert alta.status_code == 201, alta.text
    turno = alta.json()["public_id"]
    actualizar = text(
        "update appointments set price_amount = :p, addons_amount = :a where id = :id"
    )

    with pytest.raises(IntegrityError, match="ck_appointments_addons_amount"):
        async with owner_engine.begin() as conn:
            await conn.execute(
                actualizar, {"p": Decimal("100"), "a": Decimal("-1"), "id": turno}
            )
    async with owner_engine.begin() as conn:
        await conn.execute(
            actualizar, {"p": Decimal("1000"), "a": Decimal("3000"), "id": turno}
        )
    async with owner_engine.connect() as conn:
        validada = (
            await conn.execute(
                text(
                    "select convalidated from pg_constraint "
                    "where conname = 'ck_appointments_addons_amount'"
                )
            )
        ).scalar_one()
    # La revision B (f3b5d7f9a1c2) la valido.
    assert validada is True
