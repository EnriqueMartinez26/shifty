"""El export de reportes no congela el event loop.

2026-09-24, F1-07 (R2-02, R8-06; decision 19 del dueno): ``POST
/reports/export`` armaba el archivo con openpyxl/reportlab SINCRONOS dentro
del ``async def`` (el loop congelado para todos los requests del proceso),
traia cuatro entidades ORM por turno y calculaba top-5, cohortes y deuda que
el archivo no escribe. El recorte de texto del PDF era O(n^2) con
``stringWidth`` por caracter.

Ahora: el formateo de filas corre fuera del hilo del loop (Excel y PDF en
``asyncio.to_thread``, CSV en streaming, que Starlette itera en su pool), con
una consulta de columnas y un tope de filas (422 neutro arriba).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, time
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import modules.reports.exporter as exporter
import modules.reports.service as report_service
from modules.appointments.model import AppointmentStatus
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _Semilla, _tienda

DIA = date(2026, 9, 7)
CUERPO: dict[str, Any] = {"from_date": "2026-09-01", "to_date": "2026-09-10"}


async def _tienda_con_turnos(
    client: AsyncClient, test_session: AsyncSession, slug: str, cantidad: int
) -> str:
    token, store, staff, servicio = await _tienda(client, test_session, slug)
    semilla = _Semilla(test_session, store, staff)
    cliente = semilla.cliente("Ana", slug.replace("-", ""))
    await test_session.flush()  # el id del cliente nace en el flush
    for i in range(cantidad):
        await semilla.turno(
            f"{slug}-{i}",
            DIA,
            time(10 + i, 0),
            servicio,
            cliente,
            AppointmentStatus.COMPLETED,
            precio=Decimal("10000"),
        )
    return token


def _hilos_del_formateo(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """``True`` por cada fila formateada en el hilo del event loop."""
    en_el_loop: list[bool] = []
    original: Callable[[Any], str] = exporter._local_datetime

    def registrar(value: Any) -> str:
        en_el_loop.append(threading.current_thread() is threading.main_thread())
        return original(value)

    monkeypatch.setattr(exporter, "_local_datetime", registrar)
    return en_el_loop


@pytest.mark.asyncio
@pytest.mark.parametrize("formato", ["csv", "excel", "pdf"])
async def test_el_archivo_se_arma_fuera_del_hilo_del_loop(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    formato: str,
) -> None:
    token = await _tienda_con_turnos(client, test_session, f"f107-{formato}", 2)
    en_el_loop = _hilos_del_formateo(monkeypatch)

    res = await client.post(
        "/reports/export",
        headers=auth_headers(token),
        json={**CUERPO, "format": formato},
    )

    assert res.status_code == 200, res.text
    assert en_el_loop, "el export no formateo ninguna fila"
    assert not any(en_el_loop), f"el {formato} se armo en el hilo del event loop"


@pytest.mark.asyncio
async def test_el_export_no_calcula_lo_que_el_archivo_no_escribe(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = await _tienda_con_turnos(client, test_session, "f107-sin-extra", 1)

    async def prohibido(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("el export calculo top-5, cohortes o deuda")

    for nombre in (
        "_top_services",
        "_top_clients",
        "_client_cohorts",
        "_build_debt_summary",
    ):
        monkeypatch.setattr(report_service.ReportService, nombre, prohibido)

    res = await client.post(
        "/reports/export", headers=auth_headers(token), json={**CUERPO, "format": "csv"}
    )
    assert res.status_code == 200, res.text
    texto = res.content.decode("utf-8-sig")
    assert "total_appointments,1" in texto
    assert "Ana f107sinextra" in texto


@pytest.mark.asyncio
async def test_pasado_el_tope_de_filas_responde_422_neutro(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = await _tienda_con_turnos(client, test_session, "f107-tope", 3)
    monkeypatch.setattr(report_service, "EXPORT_MAX_ROWS", 2)

    res = await client.post(
        "/reports/export", headers=auth_headers(token), json={**CUERPO, "format": "csv"}
    )

    assert res.status_code == 422, res.text
    cuerpo = res.json()
    assert cuerpo["error_code"] == "EXPORT_TOO_LARGE"
    assert "2" in cuerpo["message"]


def test_el_tope_de_filas_es_el_decidido() -> None:
    assert report_service.EXPORT_MAX_ROWS == 20_000


@pytest.mark.asyncio
async def test_las_filas_del_export_son_las_del_resumen(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """La consulta por columnas escribe lo mismo que las cuatro entidades."""
    _token, store, staff, servicio = await _tienda(client, test_session, "f107-igual")
    semilla = _Semilla(test_session, store, staff)
    con_nombre = semilla.cliente("Ana", "Alvarez")
    sin_nombre = semilla.cliente("Beto", "Blanco")
    await test_session.flush()
    sin_nombre.first_name = None
    sin_nombre.last_name = None
    await semilla.turno(
        "igual-0",
        DIA,
        time(10, 0),
        servicio,
        con_nombre,
        AppointmentStatus.COMPLETED,
        precio=Decimal("12000"),
    )
    await semilla.turno(
        "igual-1",
        DIA,
        time(11, 0),
        servicio,
        sin_nombre,
        AppointmentStatus.CANCELLED,
        precio=None,
    )
    service = report_service.ReportService(test_session, store_id=store.id)
    desde, hasta = date(2026, 9, 1), date(2026, 9, 10)

    resumen = await service.get_summary(desde, hasta)
    export = await service.get_export_rows(desde, hasta)

    assert export.appointments == resumen.appointments
    assert export.stats == resumen.stats
    assert len(export.appointments) == 2
