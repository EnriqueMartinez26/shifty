"""Rafagas concurrentes sobre el fiado de UN cliente, contra Postgres real (B2-16).

2026-09-17, hallazgo B2-16: ``balance_after`` es un saldo incremental (se lee
el ultimo movimiento y se le suma el nuevo) y la unica guarda contra el
pisado es ``pg_advisory_xact_lock`` en ``modules/ledger/service.py``
(``_lock_client_ledger``). En SQLite ese lock es no-op, asi que ningun test lo
ejercia. Escenario medible sin la guarda: dos cargos simultaneos leen el
mismo saldo previo, el segundo escribe un ``balance_after`` que ignora al
primero y la deuda queda corta sin que nadie se entere.

Corre con una sesion por request (concurrencia real). En SQLite el mismo test
seria una mentira.
"""

import asyncio
import os
from decimal import Decimal
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_funcional_pagos_promos_fiado import (
    _client_id_de_una_reserva,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))
CARGO = Decimal("100.00")


async def _tienda_con_fiado(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str]:
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"ledger": True},
    )
    assert flags.status_code == 200, flags.text
    cliente = await _client_id_de_una_reserva(client, token, store)
    return token, cliente


async def _saldos(owner_engine: AsyncEngine, cliente: str) -> list[Decimal]:
    async with owner_engine.connect() as conn:
        filas = (
            await conn.execute(
                text(
                    "select balance_after from customer_ledger "
                    "where client_id = :cliente order by balance_after"
                ),
                {"cliente": cliente},
            )
        ).scalars()
        return [cast(Decimal, saldo) for saldo in filas]


@pytest.mark.asyncio
async def test_cargos_simultaneos_al_mismo_cliente_no_se_pisan(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    token, cliente = await _tienda_con_fiado(client, app_sessions, "pg-fiado-cargos")

    respuestas = await asyncio.gather(
        *(
            client.post(
                f"/ledger/customers/{cliente}/movements",
                headers=auth_headers(token),
                json={"movement_type": "charge", "amount": str(CARGO)},
            )
            for _ in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    # Ningun cargo es un conflicto: el lock los ordena, no los rechaza.
    assert codigos == [200] * RAFAGA, codigos

    # Cada movimiento vio el saldo del anterior: los saldos son 100, 200, ...
    # N*100, sin repetidos. Con el pisado habria saldos duplicados y el
    # ultimo quedaria por debajo de la suma.
    saldos = await _saldos(owner_engine, cliente)
    assert saldos == [CARGO * (i + 1) for i in range(RAFAGA)], saldos

    cuenta = await client.get(
        f"/ledger/customers/{cliente}", headers=auth_headers(token)
    )
    assert cuenta.status_code == 200, cuenta.text
    assert Decimal(cuenta.json()["balance"]) == CARGO * RAFAGA


@pytest.mark.asyncio
async def test_rafaga_de_reversas_del_mismo_movimiento_revierte_una_vez(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """N reversas del mismo movimiento: 1 exito, N-1 rechazos, cero 5xx."""
    token, cliente = await _tienda_con_fiado(client, app_sessions, "pg-fiado-rev")
    cargo = await client.post(
        f"/ledger/customers/{cliente}/movements",
        headers=auth_headers(token),
        json={"movement_type": "charge", "amount": str(CARGO)},
    )
    assert cargo.status_code == 200, cargo.text
    movimiento = cargo.json()["public_id"]

    respuestas = await asyncio.gather(
        *(
            client.post(
                f"/ledger/customers/{cliente}/movements/{movimiento}/reverse",
                headers=auth_headers(token),
            )
            for _ in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(200) == 1, codigos
    # "Ese movimiento ya fue revertido." (ValidationException -> 422).
    assert set(codigos) <= {200, 422}, codigos

    assert await _saldos(owner_engine, cliente) == [Decimal("0.00"), CARGO]
