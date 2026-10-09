"""Nombre y apellido que carga el superadmin rechazan invisibles (regla 19).

2026-10-01, sintoma: ``StoreAdminCreate`` y ``UserGlobalUpdate`` no corrian
``reject_control_chars`` en ``first_name``/``last_name``. El soporte global (o
quien le pase el texto) podia guardar un U+202E o un zero-width en el nombre de
un admin de tienda, y ese nombre sale al panel del dueno y a sus reportes
(``_report_client_name``): spoofing visual tipo Trojan Source. ``/users`` ya lo
rechazaba (AUD2-B5-03) y ``test_entrada_hostil.py`` lo excluia como "no se
publica" sin que nadie lo hubiera decidido.

La guarda va solo en los schemas de ENTRADA: las respuestas siguen leyendo una
fila legada con un invisible (mismo criterio que ``UserCreate``/``UserUpdate``).
"""

from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_superadmin_catalog import _global_admin

VENENOS = [
    pytest.param("Nombre" + chr(0), id="nul"),
    pytest.param("Nombre" + chr(0x202E) + "otro", id="bidi-override"),
    pytest.param("Nom" + chr(0x200B) + "bre", id="zero-width"),
]
CAMPOS = ["first_name", "last_name"]


def _admin(**cambios: str) -> dict[str, str]:
    cuerpo = {
        "email": "admin-nuevo@test.com",
        "password": "Password123!",
        "first_name": "Duenio",
        "last_name": "Nuevo",
    }
    cuerpo.update(cambios)
    return cuerpo


async def _tienda(client: AsyncClient, token: str) -> str:
    res = await client.post(
        "/superadmin/stores",
        headers=auth_headers(token),
        json={"name": "Barberia Nueva", "slug": "barberia-nueva"},
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("campo", CAMPOS)
@pytest.mark.parametrize("veneno", VENENOS)
async def test_el_alta_de_un_admin_rechaza_invisibles_en_el_nombre(
    client: AsyncClient, test_session: AsyncSession, campo: str, veneno: str
) -> None:
    token = await _global_admin(
        client, test_session, slug="sa-nombre-alta", email="sa-nombre-alta@test.com"
    )
    tienda = await _tienda(client, token)

    res = await client.post(
        f"/superadmin/stores/{tienda}/admins",
        headers=auth_headers(token),
        json=_admin(**{campo: veneno}),
    )

    assert res.status_code == 422, res.text
    usuarios = await client.get(
        f"/superadmin/stores/{tienda}/users", headers=auth_headers(token)
    )
    assert usuarios.status_code == 200, usuarios.text
    assert all(u["email"] != "admin-nuevo@test.com" for u in usuarios.json())


@pytest.mark.asyncio
@pytest.mark.parametrize("campo", CAMPOS)
@pytest.mark.parametrize("veneno", VENENOS)
async def test_la_edicion_global_rechaza_invisibles_en_el_nombre(
    client: AsyncClient, test_session: AsyncSession, campo: str, veneno: str
) -> None:
    token = await _global_admin(
        client, test_session, slug="sa-nombre-edit", email="sa-nombre-edit@test.com"
    )
    tienda = await _tienda(client, token)
    alta = await client.post(
        f"/superadmin/stores/{tienda}/admins",
        headers=auth_headers(token),
        json=_admin(),
    )
    assert alta.status_code == 201, alta.text
    public_id = cast(str, alta.json()["public_id"])

    res = await client.patch(
        f"/superadmin/users/{public_id}",
        headers=auth_headers(token),
        json={campo: veneno},
    )

    assert res.status_code == 422, res.text
    ok = await client.patch(
        f"/superadmin/users/{public_id}",
        headers=auth_headers(token),
        json={campo: "Ramon"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()[campo] == "Ramon"
