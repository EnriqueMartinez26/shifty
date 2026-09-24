"""Las cohortes de clientes cuestan lo que el rango, con los mismos numeros.

2026-09-24, plan de rendimiento F3-05 (hallazgo R2-06). ``_client_cohorts``
agrupaba por ``client_id`` TODOS los turnos de la tienda anteriores al fin
del rango (``starts_at < fin``, sin cota inferior) para saber la primera
visita de cada cliente. Cada ``/reports/summary`` —tambien el de 7 dias que
pide el Dashboard— recorria la historia entera de la tienda, y con anos de
turnos rozaba el ``statement_timeout`` de 30 s.

Ahora se parte de los clientes del rango (``COUNT(DISTINCT client_id)`` sobre
el indice ``(store_id, starts_at)``) y "nuevo" es ``NOT EXISTS`` un turno
anterior del mismo cliente en la tienda; "inactivo" sale de los clientes de la
tienda con ALGUN turno anterior (``EXISTS`` por ``ix_appointments_client_id``,
que se detiene en el primero) menos los recurrentes.

La prueba de equivalencia compara contra una copia de la consulta vieja (el
oraculo) sobre una tienda con historia en varios rangos y con y sin filtro de
profesional. El plan en Postgres lo fija
``tests/postgres/test_pg_cohortes_acotadas.py``.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import and_, case, event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from core.utils import local_day_start
from modules.appointments.model import Appointment, AppointmentStatus
from modules.reports.schemas import ReportClientStats
from modules.reports.service import ReportService
from modules.staff.model import Staff
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _Semilla, _tienda

RANGOS = (
    (date(2026, 9, 1), date(2026, 9, 10)),
    (date(2026, 8, 1), date(2026, 8, 31)),
    (date(2026, 9, 5), date(2026, 9, 5)),
    (date(2026, 9, 11), date(2026, 9, 30)),
)


async def _cohortes_de_referencia(
    db: AsyncSession,
    store_id: str,
    start_dt: datetime,
    end_dt: datetime,
    staff_id: str | None,
) -> ReportClientStats:
    """La consulta de ``_client_cohorts`` antes de F3-05, tal cual (oraculo)."""
    por_cliente = (
        select(
            func.min(Appointment.starts_at).label("first_seen"),
            func.max(case((Appointment.starts_at >= start_dt, 1), else_=0)).label(
                "in_range"
            ),
        )
        .join(User, Appointment.client_id == User.id)
        .where(
            Appointment.client_id.is_not(None),
            Appointment.starts_at < end_dt,
            Appointment.store_id == store_id,
        )
        .group_by(Appointment.client_id)
    )
    if staff_id:
        por_cliente = por_cliente.where(Appointment.staff_id == staff_id)
    clientes = por_cliente.subquery()
    en_rango = clientes.c.in_range == 1

    def _contar(condicion: Any) -> Any:
        return func.coalesce(func.sum(case((condicion, 1), else_=0)), 0)

    result = await db.execute(
        select(
            _contar(en_rango),
            _contar(and_(en_rango, clientes.c.first_seen >= start_dt)),
            _contar(and_(clientes.c.in_range == 0, clientes.c.first_seen < start_dt)),
        )
    )
    total, nuevos, inactivos = (int(valor or 0) for valor in result.one())
    return ReportClientStats(
        total_clients=total,
        new_clients=nuevos,
        returning_clients=max(total - nuevos, 0),
        inactive_clients=inactivos,
    )


async def _sembrar_historia(
    client: AsyncClient, test_session: AsyncSession
) -> tuple[str, str, str, str]:
    """Clientes en cada caso de borde, con dos profesionales y otra tienda."""
    token, store, staff, corto = await _tienda(client, test_session, "f305-coh")
    otro = Staff(
        store_id=store.id, first_name="Otro", last_name="O", display_name="Otro"
    )
    test_session.add(otro)
    await test_session.commit()
    semilla = _Semilla(test_session, store, staff)
    nombres = ("Ana", "Beto", "Carla", "Dario", "Elena", "Fede", "Gabi", "Hugo")
    clientes = {n: semilla.cliente(n, "F305") for n in (*nombres, "Ines", "Juan")}
    await test_session.commit()
    completado = AppointmentStatus.COMPLETED
    turnos: list[tuple[str, date, time, AppointmentStatus, Staff]] = [
        ("Ana", date(2026, 8, 3), time(10, 0), completado, staff),  # vuelve
        ("Ana", date(2026, 9, 2), time(10, 0), completado, staff),
        ("Beto", date(2026, 9, 3), time(10, 0), completado, staff),  # nuevo
        ("Carla", date(2025, 3, 3), time(10, 0), completado, staff),  # inactiva
        ("Carla", date(2026, 8, 20), time(10, 0), completado, otro),
        ("Dario", date(2026, 10, 1), time(10, 0), completado, staff),  # despues
        ("Elena", date(2026, 7, 1), time(10, 0), completado, staff),  # antes+despues
        ("Elena", date(2026, 9, 20), time(10, 0), completado, staff),
        ("Fede", date(2026, 9, 9), time(10, 0), completado, otro),  # rango+despues
        ("Fede", date(2026, 9, 25), time(10, 0), completado, staff),
        ("Gabi", date(2026, 9, 4), time(10, 0), AppointmentStatus.CANCELLED, staff),
        ("Hugo", date(2026, 8, 10), time(10, 0), completado, otro),  # otro prof.
        ("Hugo", date(2026, 9, 5), time(10, 0), completado, staff),
        ("Ines", date(2026, 9, 1), time(0, 0), completado, staff),  # justo al inicio
        ("Ines", date(2026, 8, 31), time(23, 59), completado, otro),
        ("Juan", date(2026, 9, 11), time(0, 0), completado, staff),  # justo al fin
    ]
    for indice, (nombre, dia, hora, estado, profesional) in enumerate(turnos):
        semilla.staff = profesional
        await semilla.turno(
            f"f305-{indice}", dia, hora, corto, clientes[nombre], estado,
            precio=Decimal("10000"),
        )  # fmt: skip
    # Turnos sin cliente vinculado, antes y dentro del rango: nunca cuentan.
    for indice, dia in enumerate((date(2026, 8, 1), date(2026, 9, 2))):
        inicio = local_day_start(dia)
        test_session.add(
            Appointment(
                service_id=corto.id,
                staff_id=staff.id,
                store_id=store.id,
                client_id=None,
                client_name="Sin cuenta",
                starts_at=inicio,
                ends_at=inicio,
                duration_minutes=30,
                status=completado.value,
                idempotency_key=f"f305-huerfano-{indice}",
            )
        )
    await test_session.commit()
    # Otra tienda con historia propia en los mismos dias.
    _, ajena, staff_ajeno, corto_ajeno = await _tienda(
        client, test_session, "f305-ajena"
    )
    ajena_semilla = _Semilla(test_session, ajena, staff_ajeno)
    zoe = ajena_semilla.cliente("Zoe", "Ajena")
    await test_session.commit()
    for indice, dia in enumerate((date(2026, 8, 3), date(2026, 9, 3))):
        await ajena_semilla.turno(
            f"f305-ajena-{indice}", dia, time(10, 0), corto_ajeno, zoe, completado,
            precio=Decimal("10000"),
        )  # fmt: skip
    return token, store.id, staff.id, otro.id


@pytest.mark.asyncio
async def test_las_cohortes_dan_lo_mismo_que_la_consulta_historica(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, store_id, staff_id, otro_id = await _sembrar_historia(client, test_session)
    reportes = ReportService(test_session, store_id=store_id)
    comparados = 0
    for desde, hasta in RANGOS:
        start_dt, end_dt = reportes._range_bounds(desde, hasta)
        for profesional in (None, staff_id, otro_id):
            esperado = await _cohortes_de_referencia(
                test_session, store_id, start_dt, end_dt, profesional
            )
            obtenido = await reportes._client_cohorts(
                start_dt=start_dt, end_dt=end_dt, staff_id=profesional
            )
            assert obtenido == esperado, (desde, hasta, profesional)
            comparados += 1
    assert comparados == 12
    # Y el caso principal con numeros explicitos, para que el oraculo no sea
    # el unico que sabe la respuesta: del 1 al 10 de septiembre vinieron Ana,
    # Beto, Fede, Gabi, Hugo e Ines; nuevos Beto, Fede y Gabi; inactivas
    # Carla y Elena (vinieron antes y no en el rango).
    start_dt, end_dt = reportes._range_bounds(date(2026, 9, 1), date(2026, 9, 10))
    assert await reportes._client_cohorts(
        start_dt=start_dt, end_dt=end_dt, staff_id=None
    ) == ReportClientStats(
        total_clients=6, new_clients=3, returning_clients=3, inactive_clients=2
    )


@pytest.mark.asyncio
async def test_las_cohortes_no_agrupan_la_historia_de_la_tienda(
    client: AsyncClient, test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    token, *_ = await _sembrar_historia(client, test_session)
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

    event.listen(test_engine.sync_engine, "before_cursor_execute", registrar)
    try:
        res = await client.get(
            "/reports/summary",
            params={"from_date": "2026-09-01", "to_date": "2026-09-10"},
            headers=auth_headers(token),
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", registrar)
    assert res.status_code == 200, res.text
    assert res.json()["client_stats"] == {
        "total_clients": 6,
        "new_clients": 3,
        "returning_clients": 3,
        "inactive_clients": 2,
    }
    # El top-5 de clientes agrupa por cliente DENTRO del rango y con LIMIT;
    # la cohorte vieja agrupaba toda la historia, sin tope.
    historicas = [
        s
        for s in sentencias
        if "group by appointments.client_id" in s and " limit " not in s
    ]
    assert historicas == [], f"cohortes sobre toda la historia: {historicas}"
    cohortes = [s for s in sentencias if "exists" in s]
    assert len(cohortes) == 1, cohortes
