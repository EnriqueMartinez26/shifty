"""``PATCH /stores/me`` no dice 200 cuando guarda menos de lo que le mandaron.

AUD2-B3-07, 2026-09-20. Sintoma: ``StoreUpdate.business_hours`` acepta
``Dict[str, List[BusinessHourPeriod]]`` y la restriccion ``uq_store_day_schedule``
ya no existe (la migracion ``c2d4e6f8a901`` la reemplazo por el indice no unico
``ix_store_schedules_store_day``), pero ``_replace_business_hours`` tomaba SOLO
``periods[0]`` y tiraba el resto. Un local con corte de mediodia mandaba
``{"mon": [09:00-13:00, 16:00-20:00]}``, recibia 200 y quedaba abierto 09-13
nada mas.

Soportar horario partido de verdad es decision de PRODUCTO y esta pendiente. Lo
que se arregla aca es la mentira de contrato: un 200 que guarda menos de lo
enviado. Ahora el segundo periodo da 422 con mensaje neutro, no desaparece.
"""

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


@pytest.mark.asyncio
async def test_un_segundo_periodo_en_el_dia_da_422_y_no_desaparece(
    client: AsyncClient,
) -> None:
    _store, token = await register_and_login(
        client, slug="b3-07-partido", email="b3-07-partido@example.com"
    )

    res = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={
            "business_hours": {
                "mon": [
                    {"open": "09:00:00", "close": "13:00:00"},
                    {"open": "16:00:00", "close": "20:00:00"},
                ]
            }
        },
    )
    assert res.status_code == 422, res.text

    # Y la tienda no quedo a medias: sigue sin el horario del lunes.
    actual = await client.get("/stores/me", headers=auth_headers(token))
    assert actual.status_code == 200, actual.text
    assert not [
        periodo
        for periodo in (actual.json().get("business_hours") or {}).get("mon", [])
    ]


@pytest.mark.asyncio
async def test_un_solo_periodo_por_dia_se_guarda_entero(client: AsyncClient) -> None:
    _store, token = await register_and_login(
        client, slug="b3-07-simple", email="b3-07-simple@example.com"
    )

    res = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={
            "business_hours": {
                "mon": [{"open": "09:00:00", "close": "13:00:00"}],
                "tue": [{"open": "10:00:00", "close": "18:00:00"}],
                # Un dia sin periodos es "cerrado", no una perdida de datos.
                "wed": [],
            }
        },
    )
    assert res.status_code == 200, res.text
    horarios = res.json()["business_hours"]
    assert horarios["mon"] == [{"open": "09:00", "close": "13:00"}]
    assert horarios["tue"] == [{"open": "10:00", "close": "18:00"}]
    assert horarios.get("wed", []) == []
