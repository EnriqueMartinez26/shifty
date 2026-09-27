"""B6-04 (2026-09-18): el PATCH de un servicio no podia borrar un campo opcional.

Sintoma: ``PATCH /services/{public_id} {"image_url": null}`` respondia 200 con
la imagen vieja. El router hacia ``model_dump()`` sin ``exclude_unset`` (todo
campo no enviado llegaba como ``None``) y el repositorio descartaba todo
``None``, asi que un ``null`` enviado a proposito tambien se perdia. El panel
mostraba de vuelta la imagen borrada al refrescar.

Ahora "ausente" y "null explicito" se distinguen (``exclude_unset``, mismo
criterio que B3-19): ausente no toca el campo; ``null`` lo borra, solo en las
columnas que admiten NULL. En una columna NOT NULL el ``null`` es 422, no un
409/500 de la base.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

COMPLETO = {
    "name": "Corte",
    "description": "Corte con lavado",
    "duration_minutes": 30,
    "price": 1500,
    "color": "#ff0000",
    "image_url": "https://cdn.example.com/corte.png",
    "youtube_trailer_url": "https://www.youtube.com/watch?v=abc123",
}


async def _crear(client: AsyncClient, token: str) -> dict[str, Any]:
    res = await client.post("/services/", headers=auth_headers(token), json=COMPLETO)
    assert res.status_code == 201, res.text
    return cast(dict[str, Any], res.json())


async def _leer(client: AsyncClient, token: str, public_id: str) -> dict[str, Any]:
    res = await client.get(f"/services/{public_id}", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    return cast(dict[str, Any], res.json())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "campo", ["description", "color", "image_url", "youtube_trailer_url"]
)
async def test_null_explicito_borra_el_campo_opcional(
    client: AsyncClient, campo: str
) -> None:
    _, token = await register_and_login(
        client, slug=f"b6-04-{campo.replace('_', '-')}", email=f"b6-04-{campo}@e.com"
    )
    servicio = await _crear(client, token)

    res = await client.patch(
        f"/services/{servicio['public_id']}",
        headers=auth_headers(token),
        json={campo: None},
    )
    assert res.status_code == 200, res.text
    assert res.json()[campo] is None

    guardado = await _leer(client, token, servicio["public_id"])
    assert guardado[campo] is None
    # El resto no se toco.
    for otro in COMPLETO:
        if otro != campo:
            assert guardado[otro] == servicio[otro], otro


@pytest.mark.asyncio
async def test_campo_ausente_no_se_toca(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="b6-04-ausente", email="b6-04-ausente@example.com"
    )
    servicio = await _crear(client, token)

    res = await client.patch(
        f"/services/{servicio['public_id']}",
        headers=auth_headers(token),
        json={"name": "Corte nuevo"},
    )
    assert res.status_code == 200, res.text
    guardado = await _leer(client, token, servicio["public_id"])
    assert guardado["name"] == "Corte nuevo"
    for otro in COMPLETO:
        if otro != "name":
            assert guardado[otro] == servicio[otro], otro


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "campo",
    [
        "name",
        "duration_minutes",
        "price",
        "deposit_mode",
        "deposit_type",
        "is_active",
    ],
)
async def test_null_en_columna_obligatoria_es_422(
    client: AsyncClient, campo: str
) -> None:
    _, token = await register_and_login(
        client,
        slug=f"b6-04-nn-{campo.replace('_', '-')}",
        email=f"b6-04-nn-{campo}@e.com",
    )
    servicio = await _crear(client, token)

    res = await client.patch(
        f"/services/{servicio['public_id']}",
        headers=auth_headers(token),
        json={campo: None},
    )
    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "VALIDATION_ERROR"
    guardado = await _leer(client, token, servicio["public_id"])
    assert guardado[campo] == servicio[campo]
