"""Corregirle el telefono a alguien no lo saca de todos sus dispositivos.

AUD2-B3-09, 2026-09-20. Sintoma: `core/roles.py` introdujo explicitamente la
idea de que "reenviar el mismo rol no es otorgarlo (el formulario del panel
manda el ``role`` actual en cada edicion)" -- ``assert_can_grant_role`` con
``current`` y ``assert_can_change_access`` con ``_valor(role) !=
_valor(target.role)``. ``UserRepository.update`` no recibio esa lectura: revoca
las sesiones cuando ``payload.get("role") is not None``, sin compararlo contra
el rol vigente. Como el formulario manda siempre el ``role``, corregirle el
telefono a alguien lo desloguea de todos sus dispositivos.

No rompe la regla 15 (revoca de mas, nunca de menos), pero convierte una
edicion inocua en un cierre de sesion y ensena al usuario a desconfiar del
panel. Lo que NO puede pasar es lo contrario: un cambio real de rol tiene que
seguir matando las sesiones, y eso se prueba aca abajo.
"""

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

PASSWORD = "Password123!"
EDITADO = "b309-editado@test.com"


async def _alta_y_login(client: AsyncClient, token: str) -> tuple[str, str]:
    """Crea un profesional y devuelve su ``public_id`` y su access token."""
    alta = await client.post(
        "/users/",
        headers=auth_headers(token),
        json={
            "email": EDITADO,
            "first_name": "Pro",
            "last_name": "Fesional",
            "phone": "1122334455",
            "password": PASSWORD,
            "role": "staff",
        },
    )
    assert alta.status_code == 201, alta.text

    login = await client.post(
        "/auth/login", json={"email": EDITADO, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return str(alta.json()["public_id"]), str(login.json()["access_token"])


@pytest.mark.asyncio
async def test_reenviar_el_rol_actual_no_corta_la_sesion(client: AsyncClient) -> None:
    _store, token = await register_and_login(
        client, slug="b309-mismo", email="b309-mismo@test.com"
    )
    public_id, token_editado = await _alta_y_login(client, token)
    assert (
        await client.get("/me", headers=auth_headers(token_editado))
    ).status_code == 200

    # Lo que manda el formulario del panel: el campo editado MAS el rol vigente.
    res = await client.patch(
        f"/users/{public_id}",
        headers=auth_headers(token),
        json={"phone": "1199887766", "role": "staff"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["phone"] == "1199887766"

    vive = await client.get("/me", headers=auth_headers(token_editado))
    assert vive.status_code == 200, (
        "corregir un telefono reenviando el rol actual cerro la sesion del editado"
    )


@pytest.mark.asyncio
async def test_un_cambio_real_de_rol_sigue_revocando(client: AsyncClient) -> None:
    """La guarda de la regla 15 no se puede perder por el camino."""
    _store, token = await register_and_login(
        client, slug="b309-cambio", email="b309-cambio@test.com"
    )
    public_id, token_editado = await _alta_y_login(client, token)

    res = await client.patch(
        f"/users/{public_id}",
        headers=auth_headers(token),
        json={"role": "receptionist"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["role"] == "receptionist"

    muerta = await client.get("/me", headers=auth_headers(token_editado))
    assert muerta.status_code == 401, (
        "un cambio de rol dejo viva una sesion con los permisos viejos"
    )


@pytest.mark.asyncio
async def test_una_clave_impuesta_sigue_revocando(client: AsyncClient) -> None:
    _store, token = await register_and_login(
        client, slug="b309-clave", email="b309-clave@test.com"
    )
    public_id, token_editado = await _alta_y_login(client, token)

    res = await client.patch(
        f"/users/{public_id}",
        headers=auth_headers(token),
        json={"password": "OtraPassword456!", "role": "staff"},
    )
    assert res.status_code == 200, res.text

    muerta = await client.get("/me", headers=auth_headers(token_editado))
    assert muerta.status_code == 401, (
        "una clave impuesta por el admin dejo viva la sesion anterior"
    )
