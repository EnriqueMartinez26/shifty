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
"""

from datetime import date, time

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
