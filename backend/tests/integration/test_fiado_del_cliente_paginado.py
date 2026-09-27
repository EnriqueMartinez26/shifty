"""El historial de fiado de un cliente viene acotado y con el saldo de SQL.

2026-09-20, AUD2-B2-10: ``GET /ledger/customers/{id}`` leia el historial
COMPLETO del cliente, sin ``limit`` ni paginacion, y armaba el saldo con
``movements[-1].balance_after``. Un cliente con anos de fiado devolvia miles
de filas en una sola respuesta; era el unico endpoint de lectura del grupo
sin cota (regla 9 en su intencion) y el saldo salia de traer todo a memoria
cuando se puede pedir con ``LIMIT 1`` (regla 11), que es como ya lo hace
``ledger/service.current_balance``.

B2-06 movio el RESUMEN a SQL y dejo este endpoint tal cual.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.ledger.router import LEDGER_PAGE_DEFAULT, LEDGER_PAGE_MAX
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

MOVIMIENTOS = LEDGER_PAGE_DEFAULT + 7


async def _tienda_con_deudor(
    client: AsyncClient, session: AsyncSession, *, slug: str
) -> tuple[str, str]:
    store_public_id, token = await register_and_login(
        client, slug=slug, email=f"{slug}@test.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags", headers=auth_headers(token), json={"ledger": True}
    )
    assert flags.status_code == 200, flags.text
    store = (
        await session.execute(select(Store).where(Store.public_id == store_public_id))
    ).scalar_one()
    deudor = User(
        email=f"{slug}-deudor@test.com",
        hashed_password="no-se-loguea",
        first_name="Deudor",
        last_name="Largo",
        role=UserRole.CLIENT,
        store_id=store.id,
    )
    session.add(deudor)
    await session.commit()
    return token, deudor.id


async def _cargar(
    client: AsyncClient, token: str, deudor: str, *, cuantos: int
) -> None:
    for _ in range(cuantos):
        res = await client.post(
            f"/ledger/customers/{deudor}/movements",
            headers=auth_headers(token),
            json={"movement_type": "charge", "amount": "10.00"},
        )
        assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_el_historial_viene_acotado_y_del_mas_nuevo_al_mas_viejo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, deudor = await _tienda_con_deudor(client, test_session, slug="b210-tope")
    await _cargar(client, token, deudor, cuantos=MOVIMIENTOS)

    res = await client.get(f"/ledger/customers/{deudor}", headers=auth_headers(token))

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert len(cuerpo["movements"]) == LEDGER_PAGE_DEFAULT, (
        "el endpoint devolvio el historial entero: un cliente con anos de "
        f"fiado se lleva todas sus filas en una respuesta ({MOVIMIENTOS})"
    )
    assert cuerpo["total"] == MOVIMIENTOS
    # El saldo es el del ULTIMO movimiento, no el de la ultima fila devuelta.
    assert cuerpo["balance"] == str(Decimal("10.00") * MOVIMIENTOS)
    # Mas nuevo primero: con un tope, la pagina util es la reciente.
    saldos = [Decimal(m["balance_after"]) for m in cuerpo["movements"]]
    assert saldos == sorted(saldos, reverse=True), saldos
    assert saldos[0] == Decimal("10.00") * MOVIMIENTOS


@pytest.mark.asyncio
async def test_la_segunda_pagina_sigue_donde_termino_la_primera(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, deudor = await _tienda_con_deudor(client, test_session, slug="b210-pagina")
    await _cargar(client, token, deudor, cuantos=5)

    primera = await client.get(
        f"/ledger/customers/{deudor}?limit=2", headers=auth_headers(token)
    )
    segunda = await client.get(
        f"/ledger/customers/{deudor}?limit=2&offset=2", headers=auth_headers(token)
    )

    assert primera.status_code == 200, primera.text
    assert segunda.status_code == 200, segunda.text
    ids_primera = [m["public_id"] for m in primera.json()["movements"]]
    ids_segunda = [m["public_id"] for m in segunda.json()["movements"]]
    assert len(ids_primera) == 2 and len(ids_segunda) == 2
    assert not set(ids_primera) & set(ids_segunda), "las paginas se superponen"
    # El saldo no depende de la pagina: sale de una consulta propia.
    assert primera.json()["balance"] == segunda.json()["balance"] == "50.00"
    assert primera.json()["total"] == segunda.json()["total"] == 5


@pytest.mark.asyncio
async def test_los_parametros_estan_acotados_de_los_dos_lados(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Regla 9: un solo lado deja un 500 alcanzable."""
    token, deudor = await _tienda_con_deudor(client, test_session, slug="b210-cotas")

    for query in (
        f"limit={LEDGER_PAGE_MAX + 1}",
        "limit=0",
        "offset=-1",
        "offset=100000000000000000000",
    ):
        res = await client.get(
            f"/ledger/customers/{deudor}?{query}", headers=auth_headers(token)
        )
        assert res.status_code == 422, (query, res.status_code, res.text)


@pytest.mark.asyncio
async def test_un_cliente_sin_movimientos_sigue_dando_saldo_cero(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, deudor = await _tienda_con_deudor(client, test_session, slug="b210-vacio")

    res = await client.get(f"/ledger/customers/{deudor}", headers=auth_headers(token))

    assert res.status_code == 200, res.text
    assert res.json()["balance"] == "0.00"
    assert res.json()["movements"] == []
    assert res.json()["total"] == 0
