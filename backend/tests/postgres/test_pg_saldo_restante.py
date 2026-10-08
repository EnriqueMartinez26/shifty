"""Saldo restante por turno contra Postgres (D-20261008-01).

Lo que SQLite no prueba (CLAUDE.md §4):

- Rafaga: N registros del resto del MISMO turno a la vez, cada uno con su
  clave (N clics distintos): 1 exito, N-1 conflictos, cero 5xx y una sola fila
  viva. Los serializa el lock del turno (regla 4) y la ultima defensa es el
  unico parcial ``uq_appointment_balance_payments_live``.
- RLS forzada sobre ``appointment_balance_payments``: con el rol de la app y
  sin ``WHERE store_id``, cada tienda ve solo sus restos.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import cast

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

RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))


async def _turno_con_sena(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str, str]:
    """Tienda, admin y un turno de $10.000 con $100 acreditados a mano."""
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reserva = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": service,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=12, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": f"{slug}-turno",
        },
    )
    assert reserva.status_code == 201, reserva.text
    turno = cast(str, reserva.json()["public_id"])
    sena = await client.post(
        f"/payments/{turno}/manual-confirm",
        headers=auth_headers(token),
        json={"amount": "100.00"},
    )
    assert sena.status_code == 200, sena.text
    return store, token, turno


@pytest.mark.asyncio
async def test_rafaga_de_restos_del_mismo_turno_deja_uno_solo(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    _store, token, turno = await _turno_con_sena(client, app_sessions, "pg-resto-raf")

    respuestas = await asyncio.gather(
        *(
            client.post(
                f"/payments/{turno}/remaining-payment",
                headers=auth_headers(token),
                json={"idempotency_key": f"pg-resto-raf-clave-{i:04d}"},
            )
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), [r.text for r in respuestas]
    assert codigos.count(201) == 1, codigos
    assert set(codigos) <= {201, 409}, codigos

    async with owner_engine.connect() as conn:
        vivos = (
            await conn.execute(
                text(
                    "select count(*), sum(amount) from appointment_balance_payments "
                    "where appointment_id = :t and reverted_at is null"
                ),
                {"t": turno},
            )
        ).one()
    # Un resto vivo, por el saldo entero: $10.000 - $100.
    assert vivos[0] == 1
    assert str(vivos[1]) == "9900.00"


async def _contar_restos(
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
                await conn.execute(
                    text("select count(*) from appointment_balance_payments")
                )
            ).scalar_one()
            return cast(int, total)


@pytest.mark.asyncio
async def test_cada_tienda_ve_solo_sus_restos_sin_filtro_en_la_query(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
) -> None:
    tiendas = []
    for slug in ("pg-resto-rls-a", "pg-resto-rls-b"):
        store, token, turno = await _turno_con_sena(client, app_sessions, slug)
        resto = await client.post(
            f"/payments/{turno}/remaining-payment",
            headers=auth_headers(token),
            json={"idempotency_key": f"{slug}-clave-0001", "amount": "50.00"},
        )
        assert resto.status_code == 201, resto.text
        tiendas.append(store)
    tienda_a, tienda_b = tiendas

    assert await _contar_restos(app_engine, store_id=tienda_a) == 1
    assert await _contar_restos(app_engine, store_id=tienda_b) == 1
    assert await _contar_restos(app_engine, store_id=None) == 0
    assert await _contar_restos(app_engine, store_id=None, global_admin=True) == 2
