"""El fiado solo se carga contra clientes de la propia tienda.

2026-09-17, hallazgo B2-11: ``POST /ledger/customers/{client_id}/movements``
aceptaba cualquier id con forma valida y lo persistia, asi que un admin podia
dejar una fila de fiado apuntando a un usuario de OTRA tienda. En Postgres la
RLS de ``users`` tapa la lectura, pero esta suite corre en SQLite sin RLS
(CLAUDE.md §4): ahi el resumen devolvia nombre y email del cliente ajeno en
``top_debtors``. CLAUDE.md §2 exige el filtro ``store_id`` ademas de la RLS.

Sintoma: el alta respondia 200 con un ``client_id`` de otra tienda; ahora 404.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.ledger.model import CustomerLedger
from modules.users.model import User

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.integration.test_funcional_pagos_promos_fiado import (
    _client_id_de_una_reserva,
)


async def _habilitar_fiado(client: AsyncClient, token: str) -> None:
    res = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"ledger": True},
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_no_se_carga_fiado_a_un_cliente_de_otra_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _tienda_a, token_a = await register_and_login(
        client, slug="fiado-a", email="fiado-a@test.com"
    )
    tienda_b, token_b = await register_and_login(
        client, slug="fiado-b", email="fiado-b@test.com"
    )
    await _habilitar_fiado(client, token_a)
    cliente_de_b = await _client_id_de_una_reserva(client, token_b, tienda_b)

    ajeno = await client.post(
        f"/ledger/customers/{cliente_de_b}/movements",
        headers=auth_headers(token_a),
        json={"movement_type": "charge", "amount": "100.00"},
    )
    assert ajeno.status_code == 404, ajeno.text

    inexistente = await client.post(
        "/ledger/customers/01J0000000000000000000NADA/movements",
        headers=auth_headers(token_a),
        json={"movement_type": "charge", "amount": "100.00"},
    )
    assert inexistente.status_code == 404, inexistente.text

    # Ninguna fila quedo apuntando al cliente ajeno.
    filas = await test_session.scalar(select(func.count()).select_from(CustomerLedger))
    assert filas == 0

    # Y el resumen de A no expone a nadie de B.
    resumen = await client.get("/ledger/summary", headers=auth_headers(token_a))
    assert resumen.status_code == 200, resumen.text
    assert resumen.json()["top_debtors"] == []


@pytest.mark.asyncio
async def test_el_resumen_no_resuelve_nombres_de_otra_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Guarda viva: el JOIN del resumen filtra users por store_id.

    Aun con una fila historica que apunte a un cliente ajeno (cargada antes de
    este arreglo), el nombre cae al fallback (el id) en vez de leer users de
    otra tienda.
    """
    _tienda_a, token_a = await register_and_login(
        client, slug="fiado-sa", email="fiado-sa@test.com"
    )
    tienda_b, token_b = await register_and_login(
        client, slug="fiado-sb", email="fiado-sb@test.com"
    )
    await _habilitar_fiado(client, token_a)
    cliente_de_b = await _client_id_de_una_reserva(client, token_b, tienda_b)
    store_a = await test_session.scalar(
        select(User.store_id).where(User.email == "fiado-sa@test.com")
    )
    assert store_a
    test_session.add(
        CustomerLedger(
            store_id=store_a,
            client_id=cliente_de_b,
            movement_type="charge",
            amount=Decimal("50.00"),
            balance_after=Decimal("50.00"),
        )
    )
    await test_session.commit()

    resumen = await client.get("/ledger/summary", headers=auth_headers(token_a))
    assert resumen.status_code == 200, resumen.text
    [deudor] = resumen.json()["top_debtors"]
    assert deudor["client_name"] == cliente_de_b
