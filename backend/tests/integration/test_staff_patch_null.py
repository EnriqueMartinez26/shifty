"""M2 (2026-09-30): PATCH .../schedules/{sid} con start_time null respondia 500, None >= time.

Sintoma: ``PATCH /staff/{public_id}/schedules/{schedule_id}
{"start_time": null}`` respondia 500. ``ScheduleUpdate`` declara los tres
campos como opcionales, el router hace ``model_dump(exclude_unset=True)`` y la
clave llega con ``None``: ``cambios.get("start_time", schedule.start_time)``
devuelve ``None`` y el repositorio compara ``None >= time``. Con
``day_of_week`` en null seguia hasta violar el NOT NULL de la columna.

Ahora un null explicito en esas columnas es 422, igual que en el PATCH de
servicios (B6-04), y el horario queda como estaba. Un cuerpo vacio no cambia
nada.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

DIA = (datetime.now(timezone.utc) + timedelta(days=30)).weekday()
FRANJA = {"day_of_week": DIA, "start_time": "09:00:00", "end_time": "18:00:00"}


async def _profesional_con_franja(
    client: AsyncClient, slug: str
) -> tuple[str, str, dict[str, Any]]:
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@e.com")
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@e.com")
    res = await client.post(
        f"/staff/{staff}/schedules", headers=auth_headers(token), json=FRANJA
    )
    assert res.status_code == 200, res.text
    return token, staff, cast(dict[str, Any], res.json())


async def _franjas(client: AsyncClient, token: str, staff: str) -> list[Any]:
    res = await client.get(f"/staff/{staff}", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    return list(res.json()["schedules"])


@pytest.mark.asyncio
@pytest.mark.parametrize("campo", ["day_of_week", "start_time", "end_time"])
async def test_null_en_campo_obligatorio_de_la_franja_es_422(
    client: AsyncClient, campo: str
) -> None:
    token, staff, franja = await _profesional_con_franja(
        client, f"m2-nn-{campo.replace('_', '-')}"
    )

    res = await client.patch(
        f"/staff/{staff}/schedules/{franja['public_id']}",
        headers=auth_headers(token),
        json={campo: None},
    )
    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "VALIDATION_ERROR"
    # El horario quedo intacto.
    assert await _franjas(client, token, staff) == [franja]


@pytest.mark.asyncio
async def test_cuerpo_vacio_no_cambia_la_franja(client: AsyncClient) -> None:
    token, staff, franja = await _profesional_con_franja(client, "m2-vacio")

    res = await client.patch(
        f"/staff/{staff}/schedules/{franja['public_id']}",
        headers=auth_headers(token),
        json={},
    )
    assert res.status_code == 200, res.text
    assert res.json() == franja
    assert await _franjas(client, token, staff) == [franja]
