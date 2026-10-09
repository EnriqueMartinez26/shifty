"""El historial del fiado dice que movimiento es una reversa y cual ya se revirtio.

Decision de Mateo (2026-10-03): el fiado TIENE que poder revertir un
movimiento desde la pantalla. ``POST .../movements/{id}/reverse`` ya existia,
pero ``LedgerMovementResponse`` no exponia ``reverses_id`` ni si el movimiento
ya estaba revertido, asi que el panel no podia saber a cual ofrecerle
"Revertir" (el backend responde 422 a una reversa de una reversa o a una
segunda reversa).

Contrato aditivo: ``reverses_id`` (el original que anula, o null) y
``reversed`` (alguien de ESTA tienda lo anulo). ``reversed`` sale de SQL con un
EXISTS en la misma consulta de la pagina: sin una consulta por movimiento
(regla 12) y con el filtro ``store_id`` (§2, multi-tenant).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from modules.ledger.model import CustomerLedger
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.integration.test_funcional_pagos_promos_fiado import (
    _client_id_de_una_reserva,
)


async def _tienda_con_fiado(client: AsyncClient, slug: str) -> tuple[str, str]:
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@test.com")
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"ledger": True},
    )
    assert flags.status_code == 200, flags.text
    return token, await _client_id_de_una_reserva(client, token, store)


async def _cargo(client: AsyncClient, token: str, cliente: str, monto: str) -> Any:
    respuesta = await client.post(
        f"/ledger/customers/{cliente}/movements",
        headers=auth_headers(token),
        json={"movement_type": "charge", "amount": monto},
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


async def _revertir(client: AsyncClient, token: str, cliente: str, mov: str) -> Any:
    respuesta = await client.post(
        f"/ledger/customers/{cliente}/movements/{mov}/reverse",
        headers=auth_headers(token),
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


async def _historial(client: AsyncClient, token: str, cliente: str) -> Any:
    respuesta = await client.get(
        f"/ledger/customers/{cliente}", headers=auth_headers(token)
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


@pytest.mark.asyncio
async def test_el_alta_y_la_reversa_devuelven_los_campos_nuevos(
    client: AsyncClient,
) -> None:
    token, cliente = await _tienda_con_fiado(client, "rev-campos")

    cargo = await _cargo(client, token, cliente, "100.00")
    assert cargo["reverses_id"] is None
    assert cargo["reversed"] is False

    reversa = await _revertir(client, token, cliente, cargo["public_id"])
    assert reversa["reverses_id"] == cargo["public_id"]
    # Una reversa no se revierte: nunca figura como revertida.
    assert reversa["reversed"] is False


@pytest.mark.asyncio
async def test_el_historial_marca_el_revertido_y_la_reversa(
    client: AsyncClient,
) -> None:
    token, cliente = await _tienda_con_fiado(client, "rev-historial")
    revertido = await _cargo(client, token, cliente, "100.00")
    vigente = await _cargo(client, token, cliente, "50.00")
    reversa = await _revertir(client, token, cliente, revertido["public_id"])

    por_id = {
        item["public_id"]: item
        for item in (await _historial(client, token, cliente))["movements"]
    }

    assert por_id[revertido["public_id"]]["reversed"] is True
    assert por_id[revertido["public_id"]]["reverses_id"] is None
    assert por_id[vigente["public_id"]]["reversed"] is False
    assert por_id[vigente["public_id"]]["reverses_id"] is None
    assert por_id[reversa["public_id"]]["reversed"] is False
    assert por_id[reversa["public_id"]]["reverses_id"] == revertido["public_id"]


class _Sentencias:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.sentencias: list[str] = []

    def _registrar(self, *args: Any) -> None:
        self.sentencias.append(" ".join(str(args[2]).lower().split()))

    def __enter__(self) -> list[str]:
        event.listen(self.engine.sync_engine, "before_cursor_execute", self._registrar)
        return self.sentencias

    def __exit__(self, *_: object) -> None:
        event.remove(self.engine.sync_engine, "before_cursor_execute", self._registrar)


def _sobre_el_fiado(sentencias: list[str]) -> list[str]:
    return [s for s in sentencias if "customer_ledger" in s]


@pytest.mark.asyncio
async def test_reversed_no_cuesta_una_consulta_por_movimiento(
    client: AsyncClient, test_engine: AsyncEngine
) -> None:
    """Regla 12: la marca sale de la consulta de la pagina, no de un SELECT
    por fila. Las consultas al fiado son las mismas con 2 que con 8
    movimientos."""
    token, cliente = await _tienda_con_fiado(client, "rev-n-mas-1")
    uno = await _cargo(client, token, cliente, "10.00")
    await _revertir(client, token, cliente, uno["public_id"])

    with _Sentencias(test_engine) as pocas:
        await _historial(client, token, cliente)

    for _ in range(3):
        otro = await _cargo(client, token, cliente, "10.00")
        await _revertir(client, token, cliente, otro["public_id"])

    with _Sentencias(test_engine) as muchas:
        historial = await _historial(client, token, cliente)

    assert len(historial["movements"]) == 8
    assert len(_sobre_el_fiado(muchas)) == len(_sobre_el_fiado(pocas))
    # La marca va en la consulta de la pagina, filtrada por tienda.
    pagina = [
        s for s in _sobre_el_fiado(muchas) if "exists" in s and "reverses_id" in s
    ]
    assert len(pagina) == 1, _sobre_el_fiado(muchas)
    assert pagina[0].count("store_id") >= 2, pagina[0]


@pytest.mark.asyncio
async def test_una_reversa_de_otra_tienda_no_marca_el_movimiento(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """La RLS lo tapa en Postgres; el EXISTS lleva igual su ``store_id``
    (defensa en profundidad, §2). Una fila de otra tienda que apunte al
    movimiento (imposible por la API) no lo hace figurar como revertido."""
    token, cliente = await _tienda_con_fiado(client, "rev-propia")
    await register_and_login(client, slug="rev-ajena", email="rev-ajena@test.com")
    cargo = await _cargo(client, token, cliente, "100.00")

    otra_tienda = await test_session.scalar(
        select(Store.id).where(Store.slug == "rev-ajena")
    )
    assert otra_tienda is not None
    test_session.add(
        CustomerLedger(
            store_id=otra_tienda,
            client_id=cliente,
            movement_type="adjustment",
            amount=Decimal("-100.00"),
            balance_after=Decimal("0.00"),
            reverses_id=cargo["public_id"],
        )
    )
    await test_session.commit()

    movimientos = (await _historial(client, token, cliente))["movements"]

    assert [m["reversed"] for m in movimientos] == [False]
