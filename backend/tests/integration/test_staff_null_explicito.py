"""Q1 (2026-10-01): ``PUT``/``PATCH /staff/{id}`` con null explicito respondia 200 sin cambiar nada.

Sintoma: ``StaffUpdate`` declara todos sus campos como opcionales y el handler
pasa cada uno como keyword a ``update_profile``, que trata ``None`` como "no
cambiar". ``{"email": null}`` o ``{"is_active": null}`` devolvian 200 y el
profesional quedaba igual: el cliente creia haber borrado o desactivado algo
que seguia ahi. Las columnas son NOT NULL salvo ``email``, que en una persona
es su login.

Ahora un null explicito en esos campos es 422 por PUT y por PATCH
(D-20260930-03) y el profesional queda como estaba. Un campo ausente sigue
siendo "no cambiar": ``{}`` responde 200.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

CAMPOS = (
    "first_name",
    "last_name",
    "display_name",
    "email",
    "is_active",
    "service_ids",
)


async def _profesional(client: AsyncClient, slug: str) -> tuple[str, str]:
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@e.com")
    servicio = await create_service(client, token)
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@e.com")
    return token, staff


async def _leer(client: AsyncClient, token: str, staff: str) -> dict[str, Any]:
    res = await client.get(f"/staff/{staff}", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    return cast(dict[str, Any], res.json())


@pytest.mark.asyncio
@pytest.mark.parametrize("verbo", ["put", "patch"])
@pytest.mark.parametrize("campo", CAMPOS)
async def test_null_explicito_es_422_y_no_cambia_nada(
    client: AsyncClient, verbo: str, campo: str
) -> None:
    token, staff = await _profesional(client, f"q1-{verbo}-{campo.replace('_', '-')}")
    antes = await _leer(client, token, staff)

    res = await client.request(
        verbo.upper(),
        f"/staff/{staff}",
        headers=auth_headers(token),
        json={campo: None},
    )
    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "VALIDATION_ERROR"
    assert await _leer(client, token, staff) == antes


@pytest.mark.asyncio
@pytest.mark.parametrize("verbo", ["put", "patch"])
async def test_null_junto_a_un_cambio_valido_tampoco_aplica_el_cambio(
    client: AsyncClient, verbo: str
) -> None:
    token, staff = await _profesional(client, f"q1-mezcla-{verbo}")
    antes = await _leer(client, token, staff)

    res = await client.request(
        verbo.upper(),
        f"/staff/{staff}",
        headers=auth_headers(token),
        json={"display_name": "Otro Nombre", "email": None},
    )
    assert res.status_code == 422, res.text
    assert await _leer(client, token, staff) == antes


@pytest.mark.asyncio
@pytest.mark.parametrize("verbo", ["put", "patch"])
async def test_cuerpo_vacio_no_cambia_nada(client: AsyncClient, verbo: str) -> None:
    token, staff = await _profesional(client, f"q1-vacio-{verbo}")
    antes = await _leer(client, token, staff)

    res = await client.request(
        verbo.upper(), f"/staff/{staff}", headers=auth_headers(token), json={}
    )
    assert res.status_code == 200, res.text
    assert await _leer(client, token, staff) == antes


@pytest.mark.asyncio
async def test_campo_ausente_sigue_siendo_no_cambiar(client: AsyncClient) -> None:
    token, staff = await _profesional(client, "q1-parcial")
    antes = await _leer(client, token, staff)

    res = await client.patch(
        f"/staff/{staff}",
        headers=auth_headers(token),
        json={"display_name": "Nombre Nuevo"},
    )
    assert res.status_code == 200, res.text
    despues = await _leer(client, token, staff)
    assert despues["display_name"] == "Nombre Nuevo"
    assert despues["email"] == antes["email"]
    assert despues["is_active"] == antes["is_active"]
    assert despues["service_ids"] == antes["service_ids"]
