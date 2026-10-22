"""La tienda elige el punto focal de su portada (S10.1, 2026-10-22).

La portada se recorta segun el ancho de la pantalla y, sin un punto focal, el
portal la centraba siempre: una foto con el motivo arriba o abajo quedaba
cortada. La tienda elige ``cover_position`` ("top", "center" o "bottom"; null
sin elegir) en el panel; vive en ``theme_config`` junto a ``cover_url``, sin
migracion, y sale de forma aditiva en la configuracion de la tienda y en la
vitrina publica.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

JsonDict = dict[str, Any]


async def _patch(client: AsyncClient, token: str, body: JsonDict) -> JsonDict:
    res = await client.patch("/stores/me", headers=auth_headers(token), json=body)
    assert res.status_code == 200, res.text
    return dict(res.json())


async def _leer(client: AsyncClient, token: str) -> JsonDict:
    res = await client.get("/stores/me", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    return dict(res.json())


async def _theme_config(test_session: AsyncSession, slug: str) -> JsonDict:
    test_session.expire_all()
    store = (
        await test_session.execute(select(Store).where(Store.slug == slug))
    ).scalar_one()
    return dict(store.theme_config or {})


@pytest.mark.asyncio
async def test_una_tienda_existente_arranca_sin_posicion(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="portada-default", email="portada-default@test.com"
    )

    assert (await _leer(client, token))["cover_position"] is None
    vitrina = await client.get("/public/stores/portada-default")
    assert vitrina.status_code == 200, vitrina.text
    assert vitrina.json()["cover_position"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("posicion", ["top", "center", "bottom"])
async def test_cada_posicion_se_guarda_y_se_lee(
    client: AsyncClient, test_session: AsyncSession, posicion: str
) -> None:
    slug = f"portada-{posicion}"
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@test.com")

    respuesta = await _patch(client, token, {"cover_position": posicion})

    assert respuesta["cover_position"] == posicion
    assert (await _leer(client, token))["cover_position"] == posicion
    assert (await _theme_config(test_session, slug))["cover_position"] == posicion


@pytest.mark.asyncio
async def test_la_posicion_se_cambia_y_se_borra_con_null(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    slug = "portada-cambia"
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@test.com")

    await _patch(client, token, {"cover_position": "top"})
    cambiada = await _patch(client, token, {"cover_position": "bottom"})
    assert cambiada["cover_position"] == "bottom"

    # Un PATCH que no la nombra no la toca.
    otra = await _patch(client, token, {"description": "Uñas y más"})
    assert otra["cover_position"] == "bottom"

    borrada = await _patch(client, token, {"cover_position": None})
    assert borrada["cover_position"] is None
    assert (await _leer(client, token))["cover_position"] is None
    assert (await _theme_config(test_session, slug)).get("cover_position") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("invalida", ["left", "TOP", "", "50%", 1])
async def test_una_posicion_invalida_es_422_y_no_guarda_nada(
    client: AsyncClient, test_session: AsyncSession, invalida: Any
) -> None:
    slug = "portada-invalida"
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@test.com")
    await _patch(client, token, {"cover_position": "top"})

    res = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"cover_position": invalida, "description": "No se guarda"},
    )

    assert res.status_code == 422, res.text
    leida = await _leer(client, token)
    assert leida["cover_position"] == "top"
    assert leida["description"] != "No se guarda"
    assert (await _theme_config(test_session, slug))["cover_position"] == "top"


@pytest.mark.asyncio
async def test_la_vitrina_publica_expone_la_posicion(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="portada-vitrina", email="portada-vitrina@test.com"
    )
    await _patch(client, token, {"cover_position": "bottom"})

    vitrina = await client.get("/public/stores/portada-vitrina")

    assert vitrina.status_code == 200, vitrina.text
    assert vitrina.json()["cover_position"] == "bottom"


@pytest.mark.asyncio
async def test_los_campos_de_tema_existentes_siguen_igual_junto_a_la_posicion(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    slug = "portada-junto"
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@test.com")
    portada = "https://cdn.example.com/portada.jpg"

    respuesta = await _patch(
        client,
        token,
        {
            "cover_url": portada,
            "primary_color": "#AA3366",
            "cover_position": "center",
        },
    )

    assert respuesta["cover_url"] == portada
    assert respuesta["primary_color"] == "#AA3366"
    assert respuesta["cover_position"] == "center"
    leida = await _leer(client, token)
    assert leida["cover_url"] == portada
    assert leida["primary_color"] == "#AA3366"
    theme = await _theme_config(test_session, slug)
    assert theme["cover_url"] == portada
    assert theme["cover_position"] == "center"
    vitrina = await client.get(f"/public/stores/{slug}")
    assert vitrina.status_code == 200, vitrina.text
    assert vitrina.json()["cover_url"] == portada
    assert vitrina.json()["primary_color"] == "#AA3366"
