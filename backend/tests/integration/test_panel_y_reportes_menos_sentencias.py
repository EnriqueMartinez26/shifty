"""Abrir el Dashboard cuesta la mitad de sentencias y da los mismos numeros.

2026-09-24, plan de rendimiento F3-04 (hallazgo R2-03). El Dashboard pide
cuatro endpoints (``/dashboard/summary``, ``/reports/summary`` de 7 dias,
``/reports/professionals`` y ``/reports/trend``) y entre los cuatro mandaban
~31 sentencias SQL, casi todas secuenciales sobre la misma ventana de turnos:

- el panel hacia 9 consultas (conteo de hoy, pendientes, minutos, horarios,
  clientes nuevos, dos ingresos semanales, promedio, proximos), mas 2 de
  ``selectin`` por cargar ``Staff`` como entidad en ``upcoming``;
- el resumen contaba por estado, sumaba el ingreso y la sena retenida en tres
  consultas sobre el mismo conjunto de filas, y el detalle cargaba ``Staff``
  como entidad (+2 de ``selectin``);
- el reporte por profesional traia UNA FILA POR TURNO del rango como cuatro
  entidades ORM (con los 2 ``selectin`` de ``Staff``) para contar estados y
  sumar minutos en Python.

Ahora: el panel resuelve "hoy" + pendientes + clientes nuevos en una sentencia
(``FILTER``), la semana y la anterior en otra, mas horarios y proximos (4); el
resumen agrega estado, ingreso y retenido en una sola; el reporte por
profesional cuenta y suma en SQL con ``GROUP BY staff_id``. Nada se carga como
entidad ``Staff`` (sus relaciones ``selectin`` son de otro carril, F3-01).

Se mide el service, no el request: el costo fijo de identidad lo cubre
``test_identidad_una_vez_por_request.py`` y aca no tiene que moverse la vara.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, TypeVar

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from modules.appointments.model import Appointment, AppointmentStatus
from modules.dashboard.repository import DashboardRepository
from modules.dashboard.service import DashboardService
from modules.payments.model import Payment, PaymentStatus
from modules.reports.service import ReportService
from modules.services.model import Service
from modules.staff.model import Schedule, Staff
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _Semilla, _tienda

T = TypeVar("T")

# Sentencias por endpoint despues de F3-04 (antes: 11, 10, 9 y 1 = 31).
TOPE_PANEL = 4
TOPE_RESUMEN = 6
TOPE_PROFESIONALES = 4
TOPE_TENDENCIA = 1


async def _contar(
    engine: AsyncEngine, llamada: Callable[[], Awaitable[T]]
) -> tuple[T, list[str]]:
    sentencias: list[str] = []

    def registrar(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        sentencias.append(" ".join(statement.lower().split()))

    event.listen(engine.sync_engine, "before_cursor_execute", registrar)
    try:
        resultado = await llamada()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", registrar)
    return resultado, sentencias


async def _sembrar(
    client: AsyncClient, test_session: AsyncSession
) -> tuple[str, str, Staff]:
    """Una semana con turnos de todos los estados, pagos y un proximo turno."""
    token, store, staff, corto = await _tienda(client, test_session, "f304-panel")
    test_session.add(
        Schedule(
            staff_id=staff.id,
            store_id=store.id,
            day_of_week=0,
            start_time=time(9, 0),
            end_time=time(13, 0),
        )
    )
    semilla = _Semilla(test_session, store, staff)
    ana = semilla.cliente("Ana", "F304")
    await test_session.commit()
    hoy = datetime.now(timezone.utc).date()
    estados = (
        AppointmentStatus.COMPLETED,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.ABSENT,
        AppointmentStatus.CONFIRMED,
    )
    for indice, estado in enumerate(estados):
        await semilla.turno(
            f"f304-{indice}",
            hoy - timedelta(days=indice + 1),
            time(10, 0),
            corto,
            ana,
            estado,
            precio=Decimal("10000"),
            pago=(Decimal("5000.00"), PaymentStatus.APPROVED),
        )
    await semilla.turno(
        "f304-proximo", hoy + timedelta(days=2), time(10, 0), corto, ana,
        AppointmentStatus.PENDING, precio=Decimal("10000"),
    )  # fmt: skip
    return token, store.id, staff


@pytest.mark.asyncio
async def test_abrir_el_dashboard_cuesta_la_mitad_de_sentencias(
    client: AsyncClient, test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    _, store_id, _ = await _sembrar(client, test_session)
    hoy = datetime.now(timezone.utc).date()
    desde = hoy - timedelta(days=7)
    reportes = ReportService(test_session, store_id=store_id)
    panel = DashboardService(DashboardRepository(test_session, store_id=store_id))

    resumen_panel, del_panel = await _contar(test_engine, panel.get_summary)
    resumen, del_resumen = await _contar(
        test_engine,
        lambda: reportes.get_summary(desde, hoy, page=slice(0, 50)),
    )
    profesionales, de_profesionales = await _contar(
        test_engine, lambda: reportes.get_professionals(desde, hoy)
    )
    _, de_tendencia = await _contar(test_engine, lambda: reportes.get_trend(months=6))

    # Sanidad: la carga tiene datos en cada rama que se mide.
    assert resumen_panel.upcoming_appointments, "hay un proximo turno"
    assert resumen.stats.total_appointments == 4
    assert profesionales.professionals[0].appointments == 4

    conteos = {
        "panel": len(del_panel),
        "resumen": len(del_resumen),
        "profesionales": len(de_profesionales),
        "tendencia": len(de_tendencia),
    }
    assert conteos == {
        "panel": TOPE_PANEL,
        "resumen": TOPE_RESUMEN,
        "profesionales": TOPE_PROFESIONALES,
        "tendencia": TOPE_TENDENCIA,
    }, (del_panel, del_resumen, de_profesionales)
    # Ninguna sentencia carga las relaciones de Staff (selectin de F3-01): la
    # de servicios es la unica que pasa por staff_services.
    todas = del_panel + del_resumen + de_profesionales + de_tendencia
    relaciones = [s for s in todas if "staff_services" in s]
    assert relaciones == [], relaciones
    # El reporte por profesional ya no trae una fila por turno: agrega.
    sobre_turnos = [s for s in de_profesionales if "from appointments" in s]
    assert sobre_turnos, "el reporte por profesional consulta turnos"
    assert all("group by" in s for s in sobre_turnos), sobre_turnos


@pytest.mark.asyncio
async def test_los_agregados_sin_joins_hablan_del_mismo_conjunto_de_filas(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Un turno sin cliente queda afuera y uno de servicio o profesional dado
    de baja queda adentro, como siempre.

    ``_select_in_range(join_entities=False)`` saca los joins a ``services`` y
    ``staff``: las dos FK son NOT NULL y la baja es logica (``is_active``),
    asi que no cambian el conjunto de filas. El join a ``users`` SI lo
    cambia (``client_id`` es nullable y el resumen siempre excluyo esos
    turnos), por eso se conserva.
    """
    token, store, staff, corto = await _tienda(client, test_session, "f304-filas")
    semilla = _Semilla(test_session, store, staff)
    ana = semilla.cliente("Ana", "Filas")
    retirado = Service(
        store_id=store.id,
        name="Retirado",
        duration_minutes=45,
        price=Decimal("7000"),
        is_active=False,
    )
    baja = Staff(
        store_id=store.id,
        first_name="Baja",
        last_name="B",
        display_name="Baja",
        is_active=False,
    )
    test_session.add_all([retirado, baja])
    await test_session.commit()
    dia = date(2026, 9, 2)
    await semilla.turno(
        "filas-1", dia, time(10, 0), corto, ana, AppointmentStatus.COMPLETED,
        precio=Decimal("10000"), pago=(Decimal("10000.00"), PaymentStatus.APPROVED),
    )  # fmt: skip
    await semilla.turno(
        "filas-2", dia, time(11, 0), retirado, ana, AppointmentStatus.CANCELLED,
        precio=Decimal("7000"), pago=(Decimal("3000.00"), PaymentStatus.APPROVED),
    )  # fmt: skip
    # Turno de un profesional dado de baja.
    semilla.staff = baja
    await semilla.turno(
        "filas-3", dia, time(12, 0), corto, ana, AppointmentStatus.CONFIRMED,
        precio=Decimal("10000"), pago=(Decimal("2500.00"), PaymentStatus.MANUAL_CONFIRMED),
    )  # fmt: skip
    # Turno sin cliente vinculado (client_id NULL), con pago acreditado.
    starts_at = datetime(2026, 9, 2, 16, 0, tzinfo=timezone.utc)
    huerfano = Appointment(
        service_id=corto.id,
        staff_id=staff.id,
        store_id=store.id,
        client_id=None,
        client_name="Sin cuenta",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        duration_minutes=30,
        price_amount=Decimal("10000"),
        status=AppointmentStatus.COMPLETED.value,
        idempotency_key="filas-huerfano",
    )
    test_session.add(huerfano)
    await test_session.flush()
    test_session.add(
        Payment(
            store_id=store.id,
            appointment_id=huerfano.id,
            amount=Decimal("99999.00"),
            status=PaymentStatus.APPROVED.value,
            provider="manual",
        )
    )
    await test_session.commit()

    rango = {"from_date": "2026-09-02", "to_date": "2026-09-02"}
    res = await client.get(
        "/reports/summary", params=rango, headers=auth_headers(token)
    )
    assert res.status_code == 200, res.text
    stats = res.json()["stats"]
    assert stats == {
        "total_appointments": 3,
        "completed_appointments": 1,
        "cancelled_appointments": 1,
        "pending_appointments": 0,
        "confirmed_appointments": 1,
        "absent_appointments": 0,
        "expired_appointments": 0,
        "total_revenue": 15500.0,
        "average_ticket": round(15500 / 3, 2),
        "retained_deposit_revenue": 3000.0,
    }
    res = await client.get(
        "/reports/professionals", params=rango, headers=auth_headers(token)
    )
    assert res.status_code == 200, res.text
    (activo,) = res.json()["professionals"]
    assert (activo["staff_name"], activo["appointments"], activo["revenue"]) == (
        "Pro Demo",
        2,
        13000.0,
    )
    assert (activo["completed_appointments"], activo["cancelled_appointments"]) == (
        1,
        1,
    )
    # 30 del completado; el cancelado no usa tiempo.
    assert activo["used_minutes"] == 30
