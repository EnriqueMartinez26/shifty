"""El detalle de turnos del resumen se pagina con limit/offset acotados.

2026-09-18, hallazgo B5-15: ``GET /reports/summary`` devolvia en
``appointments`` un item por turno del rango, sin tope distinto del rango
(hasta 370 dias): con 40 turnos por dia, ~14.800 objetos Pydantic por request.

Decision (OK global del usuario, sugerencia del brief): el resumen sigue
trayendo el detalle, pero paginado. ``limit``/``offset`` opcionales, ambos con
``ge`` Y ``le`` (regla 9). El default (2000) no cambia la respuesta de hoy para
rangos normales: el panel pide 7 dias por defecto, y un mes completo de una
tienda con 40 turnos por dia son ~1.240. La forma del contrato no cambia; el
total sigue en ``stats.total_appointments`` (no depende de la pagina), y un
cliente sabe que hay mas cuando ``offset + len(appointments)`` es menor.
El export sigue bajando el detalle completo.

2026-09-20, AUD2-B5-01 y AUD2-B5-02 (auditoria 2): ese corte era silencioso
(ningun campo decia que faltaban filas) y solo acotaba la SALIDA: ``_fetch_rows``
seguia trayendo el rango entero y el recorte se hacia en Python. Ahora el
detalle se pagina en SQL (``LIMIT``/``OFFSET``), los conteos por estado y las
cohortes se calculan con consultas agregadas (regla 11) y la respuesta trae
``has_more``. El cambio del panel para mostrar "N de M" es de Enrique.
"""

from datetime import date, time
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from modules.appointments.model import AppointmentStatus
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _Semilla, _tienda

DIA = date(2026, 9, 3)
RANGO = {"from_date": DIA.isoformat(), "to_date": DIA.isoformat()}


@pytest.mark.asyncio
async def test_el_detalle_del_resumen_se_pagina_sin_cambiar_los_totales(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, store, staff, servicio = await _tienda(client, test_session, "b515")
    semilla = _Semilla(test_session, store, staff)
    cliente = semilla.cliente("Ana", "Paginada")
    await test_session.commit()
    turnos = [
        await semilla.turno(
            f"t{hora}",
            DIA,
            time(hora, 0),
            servicio,
            cliente,
            AppointmentStatus.CONFIRMED,
            precio=None,
        )
        for hora in (9, 10, 11)
    ]
    headers = auth_headers(token)

    async def detalle(**pagina: int) -> tuple[list[str], int]:
        res = await client.get(
            "/reports/summary", params={**RANGO, **pagina}, headers=headers
        )
        assert res.status_code == 200, res.text
        cuerpo = res.json()
        ids = [t["public_id"] for t in cuerpo["appointments"]]
        return ids, cuerpo["stats"]["total_appointments"]

    # Sin parametros: la respuesta de siempre.
    assert await detalle() == (turnos, 3)
    # Paginas: el detalle se corta, los totales no.
    assert await detalle(limit=2) == (turnos[:2], 3)
    assert await detalle(limit=2, offset=2) == (turnos[2:], 3)
    assert await detalle(offset=3) == ([], 3)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pagina",
    [
        {"limit": 0},
        {"limit": 5001},
        {"offset": -1},
        {"offset": 100_001},
        {"offset": 10**20},
    ],
)
async def test_limit_y_offset_tienen_cota_por_los_dos_lados(
    client: AsyncClient, test_session: AsyncSession, pagina: dict[str, int]
) -> None:
    token, *_ = await _tienda(client, test_session, "b515-cotas")
    res = await client.get(
        "/reports/summary", params={**RANGO, **pagina}, headers=auth_headers(token)
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_el_resumen_avisa_que_hay_mas_paginas(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """AUD2-B5-01: el corte tiene que ser visible en la respuesta."""
    token, store, staff, servicio = await _tienda(client, test_session, "aud2-b5-01")
    semilla = _Semilla(test_session, store, staff)
    cliente = semilla.cliente("Ana", "Cortada")
    await test_session.commit()
    for hora in (9, 10, 11):
        await semilla.turno(
            f"t{hora}",
            DIA,
            time(hora, 0),
            servicio,
            cliente,
            AppointmentStatus.CONFIRMED,
            precio=None,
        )
    headers = auth_headers(token)

    async def pagina(**params: int) -> dict[str, Any]:
        res = await client.get(
            "/reports/summary", params={**RANGO, **params}, headers=headers
        )
        assert res.status_code == 200, res.text
        return dict(res.json())

    primera = await pagina(limit=2)
    assert primera["has_more"] is True
    assert len(primera["appointments"]) == 2
    assert primera["stats"]["total_appointments"] == 3

    ultima = await pagina(limit=2, offset=2)
    assert ultima["has_more"] is False
    assert len(ultima["appointments"]) == 1

    completa = await pagina()
    assert completa["has_more"] is False
    assert len(completa["appointments"]) == 3


@pytest.mark.asyncio
async def test_el_detalle_se_recorta_en_la_base_no_en_python(
    client: AsyncClient, test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    """AUD2-B5-02: ninguna sentencia del resumen barre los turnos del rango.

    Con 370 dias de tope y 40 turnos por dia, traer el rango entero para
    devolver una pagina son ~14.800 tuplas de 4 entidades ORM. Toda sentencia
    sobre ``appointments`` tiene que agregar (regla 11) o llevar ``LIMIT``.
    """
    token, store, staff, servicio = await _tienda(client, test_session, "aud2-b5-02")
    semilla = _Semilla(test_session, store, staff)
    cliente = semilla.cliente("Ana", "Costosa")
    await test_session.commit()
    for hora in (9, 10, 11):
        await semilla.turno(
            f"t{hora}",
            DIA,
            time(hora, 0),
            servicio,
            cliente,
            AppointmentStatus.CONFIRMED,
            precio=None,
        )

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
        res = await client.get(
            "/reports/summary",
            params={**RANGO, "limit": 2},
            headers=auth_headers(token),
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _capturar)
    assert res.status_code == 200, res.text

    agregados = ("sum(", "count(", "avg(", "min(", "max(")
    sin_tope = [
        s
        for s in sentencias
        if " from appointments" in s
        and not any(f in s for f in agregados)
        and " limit " not in s
    ]
    assert sin_tope == [], sin_tope
