"""``GET /me`` devuelve nombre y apellido, leidos de la base.

2026-10-14, produccion. Sintoma: "Agregarme como profesional" abria el modal
con el nombre visible vacio aunque la cuenta del dueno tuviera nombre y
apellido. ``/me`` devolvia solo email, rol, tienda, ``public_id`` y
``is_global_admin``; el panel nunca recibia ``first_name``/``last_name`` y no
podia proponer el nombre (PR #185 ya habia quitado el respaldo al email, que
se publicaba como nombre del profesional).

El nombre sale de la fila que ``get_current_user`` relee en cada request
(regla 1), nunca del JWT: un cambio de nombre se ve en el proximo ``/me`` con
el MISMO token, sin volver a iniciar sesion.
"""

import base64
import json

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

PASSWORD = "Password123!"


def _claims(token: str) -> dict[str, object]:
    """Claims del access token, sin verificar la firma (solo para inspeccion)."""
    payload = token.split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return dict(json.loads(base64.urlsafe_b64decode(padded)))


async def _alta_y_login(
    client: AsyncClient, token: str, *, email: str, nombres: dict[str, str]
) -> tuple[str, str]:
    """Crea un profesional y devuelve su ``public_id`` y su access token."""
    alta = await client.post(
        "/users/",
        headers=auth_headers(token),
        json={"email": email, "password": PASSWORD, "role": "staff", **nombres},
    )
    assert alta.status_code == 201, alta.text

    login = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return str(alta.json()["public_id"]), str(login.json()["access_token"])


@pytest.mark.asyncio
async def test_me_devuelve_nombre_y_apellido_de_la_cuenta(client: AsyncClient) -> None:
    _store, token = await register_and_login(
        client, slug="me-nombre", email="me-nombre@test.com"
    )

    res = await client.get("/me", headers=auth_headers(token))

    assert res.status_code == 200, res.text
    body = res.json()
    # Los campos de siempre siguen ahi: el cambio es aditivo.
    assert body["email"] == "me-nombre@test.com"
    assert body["role"] == "admin"
    assert body["is_global_admin"] is False
    assert body["public_id"]
    assert body["store_id"]
    assert (body["first_name"], body["last_name"]) == ("Admin", "Demo")


@pytest.mark.asyncio
async def test_me_sin_nombre_devuelve_null(client: AsyncClient) -> None:
    _store, token = await register_and_login(
        client, slug="me-sin-nombre", email="me-sin-nombre@test.com"
    )
    _public_id, token_pro = await _alta_y_login(
        client, token, email="me-sin-nombre-pro@test.com", nombres={}
    )

    body = (await client.get("/me", headers=auth_headers(token_pro))).json()

    assert body["first_name"] is None
    assert body["last_name"] is None


@pytest.mark.asyncio
async def test_me_lee_el_nombre_de_la_base_y_no_del_token(client: AsyncClient) -> None:
    _store, token = await register_and_login(
        client, slug="me-renombre", email="me-renombre@test.com"
    )
    public_id, token_pro = await _alta_y_login(
        client,
        token,
        email="me-renombre-pro@test.com",
        nombres={"first_name": "Ana", "last_name": "Gomez"},
    )
    antes = (await client.get("/me", headers=auth_headers(token_pro))).json()
    assert (antes["first_name"], antes["last_name"]) == ("Ana", "Gomez")
    # El token no lleva el nombre: si /me lo devolviera desde ahi, no existiria.
    assert "first_name" not in _claims(token_pro)
    assert "last_name" not in _claims(token_pro)

    res = await client.patch(
        f"/users/{public_id}",
        headers=auth_headers(token),
        json={"first_name": "Analia", "last_name": "Gomez Paz"},
    )
    assert res.status_code == 200, res.text

    # MISMO token: el nombre nuevo viene de la fila releida en este request.
    despues = await client.get("/me", headers=auth_headers(token_pro))
    assert despues.status_code == 200, despues.text
    assert (despues.json()["first_name"], despues.json()["last_name"]) == (
        "Analia",
        "Gomez Paz",
    )
