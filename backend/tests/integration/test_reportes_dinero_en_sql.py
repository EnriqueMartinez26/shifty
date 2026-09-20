"""El dinero del reporte se agrega en SQL, sin cargar la lista a memoria.

2026-09-17, hallazgo B5-03: ``ReportService`` traia una fila por pago y la
sumaba en un ``defaultdict``; ``_aggregate_summary`` acumulaba
``total_revenue`` y el ingreso por servicio y por cliente recorriendo todos
los turnos del rango, y ordenaba los top-5 en Python; ``_build_debt_summary``
traia una fila por deudor, filtraba ``balance_after > 0``, sumaba, promediaba
y ordenaba en Python. Regla 11 de CLAUDE.md: dinero y cohortes se agregan en
SQL (el incidente 2026-09-04 nombra exactamente este archivo). Con el tope de
370 dias, una tienda con 40 turnos por dia cargaba ~15.000 tuplas para
producir 5 filas de top y 7 escalares.

Fija dos cosas: (a) el contrato de ``/reports/summary`` y
``/reports/professionals`` no cambia (ingreso cobrado, ticket promedio, top-5
de servicios y clientes, resumen de deuda con top-5 ordenado); (b) ninguna
sentencia sobre ``payments`` ni ``customer_ledger`` devuelve una fila por pago
o por deudor sin tope: cada una agrega (SUM/COUNT/AVG) o lleva LIMIT.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

# (nombre, movimientos) -> el saldo vigente es el balance_after del ULTIMO.
DEUDORES: list[tuple[str, list[tuple[str, str]]]] = [
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
AGREGADOS = ("sum(", "count(", "avg(", "min(", "max(")
TABLAS_DE_DINERO = ("payments", "customer_ledger")
# AUD2-B5-02: el resumen tampoco puede barrer los turnos del rango. Su
# detalle lleva LIMIT y todo lo demas agrega; /reports/professionals queda
# aparte, ahi el recorrido por profesional es el resultado.
TABLAS_DEL_RESUMEN = TABLAS_DE_DINERO + ("appointments",)


async def _sembrar_deudores(
    client: AsyncClient, test_session: AsyncSession, token: str, store_public_id: str
) -> None:
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    for indice, (nombre, movimientos) in enumerate(DEUDORES):
        first_name, last_name = nombre.split(" ", 1)
        deudor = User(
            email=f"deudor{indice}@b503.test",
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


async def _reservar_y_cobrar(
    client: AsyncClient, token: str, *, dia: datetime, servicio: str, staff: str
) -> None:
    """Tres turnos del mismo dia; se cobran dos (ingreso 20000, no 30000)."""
    ids = []
    for i, hora in enumerate((9, 10, 11)):
        res = await client.post(
            "/appointments/",
            headers=auth_headers(token),
            json={
                "service_id": servicio,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=hora, minute=0, second=0, microsecond=0
                ).isoformat(),
                "idempotency_key": f"b503-turno-{i}",
            },
        )
        assert res.status_code == 201, res.text
        ids.append(res.json()["public_id"])
    for public_id in ids[:2]:
        manual = await client.post(
            f"/payments/{public_id}/manual-confirm",
            headers=auth_headers(token),
            json={},
        )
        assert manual.status_code == 200, manual.text
        assert manual.json()["amount"] == "10000.00"


def _sin_tope(
    sentencias: list[str], tablas: tuple[str, ...] = TABLAS_DE_DINERO
) -> list[str]:
    """Sentencias sobre esas tablas que ni agregan ni acotan con LIMIT."""
    return [
        s
        for s in sentencias
        if any(t in s for t in tablas)
        and not any(f in s for f in AGREGADOS)
        and " limit " not in s
    ]


@pytest.mark.asyncio
async def test_el_dinero_del_reporte_se_agrega_en_sql(
    client: AsyncClient, test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="b503-reporte", email="b503@test.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True, "ledger": True},
    )
    assert flags.status_code == 200, flags.text
    servicio = await create_service(client, token)  # price 10000
    staff = await create_staff(client, token, servicio)
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff, target_date=dia)
    await _reservar_y_cobrar(client, token, dia=dia, servicio=servicio, staff=staff)
    await _sembrar_deudores(client, test_session, token, store_public_id)

    sentencias: list[str] = []
    sentencias_resumen: list[str] = []

    def _capturar(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        sentencias.append(" ".join(statement.lower().split()))

    fecha = dia.date().isoformat()
    rango = {"from_date": fecha, "to_date": fecha}
    event.listen(test_engine.sync_engine, "before_cursor_execute", _capturar)
    try:
        resumen = await client.get(
            "/reports/summary", params=rango, headers=auth_headers(token)
        )
        del sentencias_resumen[:]
        sentencias_resumen.extend(sentencias)
        profesionales = await client.get(
            "/reports/professionals", params=rango, headers=auth_headers(token)
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _capturar)
    assert resumen.status_code == 200, resumen.text
    assert profesionales.status_code == 200, profesionales.text
    cuerpo = resumen.json()

    # Contrato del ingreso: solo lo cobrado, y el ticket promedio sobre los 3.
    assert cuerpo["stats"]["total_appointments"] == 3
    assert cuerpo["stats"]["total_revenue"] == 20000.0
    assert cuerpo["stats"]["average_ticket"] == round(20000 / 3, 2)
    assert [
        (s["service_id"], s["appointments"], s["completed_appointments"], s["revenue"])
        for s in cuerpo["top_services"]
    ] == [(servicio, 3, 0, 20000.0)]
    # Desde el panel el cliente del turno es el propio admin: un solo bucket.
    assert [(c["appointments"], c["revenue"]) for c in cuerpo["top_clients"]] == [
        (3, 20000.0)
    ]
    assert cuerpo["top_clients"][0]["client_name"] == "Admin Demo"
    assert profesionales.json()["professionals"][0]["revenue"] == 20000.0

    # Contrato de la deuda: 7 deudores (Bruno saldado e Ines a favor no
    # cuentan; Carla cuenta por su ultimo saldo, no por la suma de sus filas).
    deuda = cuerpo["debt_summary"]
    assert deuda["debtors_count"] == 7
    assert deuda["outstanding_balance"] == 855.01
    assert deuda["average_debt"] == float(
        (Decimal("855.01") / 7).quantize(Decimal("0.01"))
    )
    assert [(d["client_name"], d["balance"]) for d in deuda["top_debtors"]] == [
        ("Ana Alvarez", 300.0),
        ("Elena Espinosa", 200.0),
        ("Fabio Ferro", 150.0),
        ("Gala Gomez", 120.0),
        ("Carla Castro", 70.01),
    ]

    # Regla 11: nada sobre payments ni customer_ledger viaja al proceso sin
    # agregar ni acotar.
    assert any("payments" in s for s in sentencias), "el reporte consulta pagos"
    assert any("customer_ledger" in s for s in sentencias), "y el fiado"
    assert _sin_tope(sentencias) == [], (
        f"consultas que traen la lista entera: {_sin_tope(sentencias)}"
    )
    # Y el resumen tampoco trae una fila por turno del rango (AUD2-B5-02).
    assert any("appointments" in s for s in sentencias_resumen), "consulta turnos"
    sueltas = _sin_tope(sentencias_resumen, TABLAS_DEL_RESUMEN)
    assert sueltas == [], f"el resumen barre el rango: {sueltas}"
