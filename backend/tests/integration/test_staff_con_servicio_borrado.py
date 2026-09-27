"""AUD2-B6-01 (2026-09-20): borrar un servicio dejaba en 500 la ficha del profesional.

Sintoma: despues de ``DELETE /services/{id}`` (204), cualquier operacion sobre
un profesional que tuviera ese servicio asignado respondia 500:
``GET /staff/{id}``, cargarle un horario, editarle el perfil, cambiarle los
servicios o darlo de baja. ``_hydrate_services`` re-consultaba los servicios
filtrando ``is_active`` y levantaba ``ValueError`` porque volvian menos filas
que ids pedidos; el router no lo atrapaba y salia por el handler de
excepciones no manejadas. El dueno no tenia forma de arreglarlo desde la app:
el endpoint que desharia la asignacion tambien reventaba.

Las lecturas ahora toleran servicios inactivos (no los muestran); la
validacion estricta sigue en las escrituras que ELIGEN servicios.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


async def _crear_servicio(client: AsyncClient, token: str, nombre: str) -> str:
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": nombre, "duration_minutes": 30, "price": 1500},
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


async def _escenario(client: AsyncClient, slug: str) -> tuple[str, str, str, str]:
    """Tienda con un profesional que hace dos servicios; uno queda borrado."""
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@example.com")
    vivo = await _crear_servicio(client, token, "Corte")
    borrado = await _crear_servicio(client, token, "Color")
    res = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": "Pro Demo",
            "first_name": "Pro",
            "last_name": "Demo",
            "email": f"pro-{slug}@example.com",
            "service_ids": [vivo, borrado],
        },
    )
    assert res.status_code == 201, res.text
    staff_id = cast(str, res.json()["public_id"])

    res = await client.delete(f"/services/{borrado}", headers=auth_headers(token))
    assert res.status_code == 204, res.text
    return token, staff_id, vivo, borrado


@pytest.mark.asyncio
async def test_la_ficha_del_profesional_abre_sin_el_servicio_borrado(
    client: AsyncClient,
) -> None:
    token, staff_id, vivo, borrado = await _escenario(client, "aud2-b6-01-ficha")

    res = await client.get(f"/staff/{staff_id}", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    assert res.json()["service_ids"] == [vivo]

    lista = await client.get("/staff/", headers=auth_headers(token))
    assert lista.status_code == 200, lista.text
    fichas = [s for s in lista.json() if s["public_id"] == staff_id]
    assert fichas and fichas[0]["service_ids"] == [vivo]
    assert borrado not in lista.text


@pytest.mark.asyncio
async def test_se_puede_seguir_operando_al_profesional(client: AsyncClient) -> None:
    token, staff_id, vivo, _ = await _escenario(client, "aud2-b6-01-oper")

    horario = await client.post(
        f"/staff/{staff_id}/schedules",
        headers=auth_headers(token),
        json={"day_of_week": 1, "start_time": "09:00:00", "end_time": "18:00:00"},
    )
    assert horario.status_code == 200, horario.text

    perfil = await client.patch(
        f"/staff/{staff_id}",
        headers=auth_headers(token),
        json={"display_name": "Pro Renombrado"},
    )
    assert perfil.status_code == 200, perfil.text

    servicios = await client.patch(
        f"/staff/{staff_id}/services",
        headers=auth_headers(token),
        json=[vivo],
    )
    assert servicios.status_code == 200, servicios.text

    baja = await client.delete(f"/staff/{staff_id}", headers=auth_headers(token))
    assert baja.status_code == 204, baja.text


@pytest.mark.asyncio
async def test_asignar_un_servicio_inexistente_sigue_siendo_error_de_entrada(
    client: AsyncClient,
) -> None:
    """La validacion estricta se queda donde el dueno ELIGE servicios."""
    token, staff_id, vivo, _ = await _escenario(client, "aud2-b6-01-estr")

    res = await client.patch(
        f"/staff/{staff_id}/services",
        headers=auth_headers(token),
        json=[vivo, "01ZZZZZZZZZZZZZZZZZZZZZZZZ"],
    )
    assert res.status_code == 422, res.text
    cuerpo: dict[str, Any] = res.json()
    assert cuerpo["error_code"] == "VALIDATION_ERROR"
