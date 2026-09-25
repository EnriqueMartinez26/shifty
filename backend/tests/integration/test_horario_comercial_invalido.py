"""``PATCH /stores/me`` valida el horario comercial en la entrada, no en la base.

Auditoria B3-03, 2026-09-16. Sintoma: ``{"business_hours": {"mon": [{"open":
"99:99", "close": "10:00"}]}}`` pasaba el patron ``^\\d{2}:\\d{2}$`` de Pydantic y
``time.fromisoformat`` levantaba ValueError en el router -> 500. Un cierre
anterior a la apertura tampoco se validaba: lo frenaba el CheckConstraint
``open_time < close_time`` como IntegrityError (409), con
``store.schedules.clear()`` ya ejecutado.

El contrato de salida no cambia: la respuesta sigue devolviendo ``"HH:MM"``.
"""

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


def _horario(open_: str, close: str) -> dict[str, object]:
    return {"business_hours": {"mon": [{"open": open_, "close": close}]}}


@pytest.mark.asyncio
async def test_horario_imposible_da_422_y_no_500(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="horario-99", email="horario-99@test.com"
    )
    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json=_horario("99:99", "10:00")
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_cierre_anterior_o_igual_a_la_apertura_da_422(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="horario-orden", email="horario-orden@test.com"
    )
    invertido = await client.patch(
        "/stores/me", headers=auth_headers(token), json=_horario("18:00", "09:00")
    )
    assert invertido.status_code == 422, invertido.text

    vacio = await client.patch(
        "/stores/me", headers=auth_headers(token), json=_horario("09:00", "09:00")
    )
    assert vacio.status_code == 422, vacio.text

    # El horario que tenia la tienda no se toco por el intento fallido.
    actual = await client.get("/stores/me", headers=auth_headers(token))
    assert actual.status_code == 200, actual.text
    assert actual.json()["business_hours"]["mon"] == []


@pytest.mark.asyncio
async def test_horario_valido_se_guarda_y_se_devuelve_en_hh_mm(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="horario-ok", email="horario-ok@test.com"
    )
    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json=_horario("09:00", "18:00")
    )
    assert res.status_code == 200, res.text
    esperado = [{"open": "09:00", "close": "18:00"}]
    assert res.json()["business_hours"]["mon"] == esperado

    leido = await client.get("/stores/me", headers=auth_headers(token))
    assert leido.status_code == 200, leido.text
    assert leido.json()["business_hours"]["mon"] == esperado
    assert leido.json()["business_hours"]["tue"] == []
