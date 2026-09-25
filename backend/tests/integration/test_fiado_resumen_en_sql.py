"""El resumen del fiado se agrega en SQL, sin cargar la lista de deudores.

2026-09-16, hallazgo B2-06: ``get_ledger_summary`` traia a memoria el ultimo
movimiento de CADA cliente de la tienda (sin filtro de saldo ni LIMIT) y
calculaba total, promedio y top 5 en Python. Regla 11 de CLAUDE.md: dinero y
cohortes se agregan en SQL; el costo crecia con la cantidad de clientes de la
tienda, no con los 5 que se devuelven.

Fija dos cosas: (a) el contrato de ``LedgerSummaryResponse`` no cambia (total,
cantidad, promedio redondeado, top 5 ordenado, nombres resueltos); (b) ninguna
sentencia sobre ``customer_ledger`` devuelve una fila por deudor sin tope: cada
una agrega (SUM/COUNT/AVG) o lleva LIMIT.
"""

from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

# (nombre, movimientos) -> el saldo vigente es el balance_after del ULTIMO.
CLIENTES: list[tuple[str, list[tuple[str, str]]]] = [
    ("Ana Alvarez", [("charge", "300.00")]),
    ("Bruno Blanco", [("charge", "100.00"), ("payment", "100.00")]),  # saldado
    ("Carla Castro", [("charge", "50.00"), ("charge", "20.01")]),  # vigente 70.01
    ("Dario Diaz", [("charge", "10.00")]),
    ("Elena Espinosa", [("charge", "200.00")]),
    ("Fabio Ferro", [("charge", "150.00")]),
    ("Gala Gomez", [("charge", "120.00")]),
    ("Hugo Herrera", [("charge", "5.00")]),
    ("Ines Ibarra", [("charge", "80.00"), ("payment", "100.00")]),  # a favor
]
AGREGADOS = ("sum(", "count(", "avg(")


async def _sembrar_deudores(
    client: AsyncClient, test_session: AsyncSession, token: str, store_public_id: str
) -> None:
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    for indice, (nombre, movimientos) in enumerate(CLIENTES):
        first_name, last_name = nombre.split(" ", 1)
        deudor = User(
            email=f"deudor{indice}@b206.test",
            hashed_password="no-se-loguea",
            first_name=first_name,
            last_name=last_name,
            role=UserRole.CLIENT,
            store_id=store.id,
        )
        test_session.add(deudor)
        await test_session.commit()
        for tipo, monto in movimientos:
            res = await client.post(
                f"/ledger/customers/{deudor.id}/movements",
                headers=auth_headers(token),
                json={"movement_type": tipo, "amount": monto},
            )
            assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_el_resumen_del_fiado_se_agrega_en_sql(
    client: AsyncClient, test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="b206-fiado", email="b206@test.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags", headers=auth_headers(token), json={"ledger": True}
    )
    assert flags.status_code == 200, flags.text
    await _sembrar_deudores(client, test_session, token, store_public_id)

    sentencias: list[str] = []

    def _capturar(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        sentencias.append(" ".join(statement.lower().split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", _capturar)
    try:
        resumen = await client.get("/ledger/summary", headers=auth_headers(token))
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _capturar)
    assert resumen.status_code == 200, resumen.text
    cuerpo = resumen.json()

    # Contrato: 7 deudores (Bruno saldado e Ines a favor no cuentan; Carla
    # cuenta por su ultimo saldo, no por la suma de sus filas).
    assert cuerpo["debtors_count"] == 7
    assert cuerpo["total_balance"] == "855.01"
    # 855.01 / 7 = 122.1442857...: redondeado a 2 decimales.
    assert cuerpo["average_balance"] == str(
        (Decimal("855.01") / 7).quantize(Decimal("0.01"))
    )
    assert cuerpo["total_movements"] == 12
    assert [(d["client_name"], d["balance"]) for d in cuerpo["top_debtors"]] == [
        ("Ana Alvarez", "300.00"),
        ("Elena Espinosa", "200.00"),
        ("Fabio Ferro", "150.00"),
        ("Gala Gomez", "120.00"),
        ("Carla Castro", "70.01"),
    ]
    assert all(d["last_movement_at"] for d in cuerpo["top_debtors"])

    # Regla 11: nada sobre customer_ledger viaja al proceso sin agregar ni acotar.
    sobre_ledger = [s for s in sentencias if "customer_ledger" in s]
    assert sobre_ledger, "el resumen tiene que consultar el ledger"
    sin_tope = [
        s
        for s in sobre_ledger
        if not any(f in s for f in AGREGADOS) and " limit " not in s
    ]
    assert sin_tope == [], f"consultas que traen la lista entera: {sin_tope}"
