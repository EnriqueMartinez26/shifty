"""Un dia de consulta tiene que tener dia siguiente: 9999-12-31 es 422.

2026-09-24, revision de perf/f4-back. Sintoma: la agenda del dia, la
busqueda de turnos y los reportes cortan un dia local con
``local_day_start(dia + 1)``. Con 9999-12-31 ese dia siguiente no existe y
salia 500 (``OverflowError``). Es la unica fecha que desborda: 0001-01-01 y
cualquier otra respondian bien, y siguen igual.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

ULTIMO = "9999-12-31"
PRIMERO = "0001-01-01"


@pytest.mark.asyncio
async def test_el_ultimo_dia_representable_es_422_y_el_resto_sigue(
    client: AsyncClient,
) -> None:
    _store, token = await register_and_login(
        client, slug="dia-siguiente", email="dia-siguiente@t.com"
    )
    headers = auth_headers(token)
    rango = {"from_date": ULTIMO, "to_date": ULTIMO}

    pedidos = [
        ("GET", "/appointments/", {"date": ULTIMO}, None),
        ("GET", "/appointments/search", rango, None),
        (
            "GET",
            "/appointments/search",
            {"from_date": PRIMERO, "to_date": ULTIMO},
            None,
        ),
        ("GET", "/reports/summary", rango, None),
        ("GET", "/reports/professionals", rango, None),
        ("POST", "/reports/export", None, {"format": "csv", **rango}),
    ]
    for metodo, url, params, cuerpo in pedidos:
        res = await client.request(
            metodo, url, params=params, json=cuerpo, headers=headers
        )
        assert res.status_code == 422, (url, params, cuerpo, res.text)

    for url, params in (
        ("/appointments/", {"date": PRIMERO}),
        ("/appointments/search", {"from_date": PRIMERO, "to_date": PRIMERO}),
        ("/reports/summary", {"from_date": PRIMERO, "to_date": PRIMERO}),
    ):
        res = await client.get(url, params=params, headers=headers)
        assert res.status_code == 200, (url, res.text)


@pytest.mark.asyncio
async def test_disponibilidad_del_panel_en_los_dias_extremos_422(
    client: AsyncClient,
) -> None:
    """``GET /appointments/availability`` arma la grilla con el dia anterior
    y el siguiente (turnos que cruzan la medianoche): con un profesional que
    atiende ese dia, 9999-12-31 y 0001-01-01 desbordaban (500), con token y
    sin el. El resto de los dias no cambia."""
    _store, token = await register_and_login(
        client, slug="dia-grilla", email="dia-grilla@t.com"
    )
    headers = auth_headers(token)
    servicio = await create_service(client, token)
    staff = await create_staff(client, token, servicio, email="pro-dia-grilla@t.com")
    for dia_semana in range(7):
        horario = await client.post(
            f"/staff/{staff}/schedules",
            headers=headers,
            json={
                "day_of_week": dia_semana,
                "start_time": "00:00:00",
                "end_time": "23:59:00",
            },
        )
        assert horario.status_code == 200, horario.text

    for auth in (headers, {}):
        for dia, esperado in (
            (ULTIMO, 422),
            (PRIMERO, 422),
            ("9999-12-30", 200),
            ("0001-01-02", 200),
        ):
            res = await client.get(
                "/appointments/availability",
                params={"service_id": servicio, "date": dia},
                headers=auth,
            )
            assert res.status_code == esperado, (dia, bool(auth), res.text[:200])
