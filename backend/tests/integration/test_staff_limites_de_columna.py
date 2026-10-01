"""Los nombres del personal no pasan el largo de su columna (regla 20).

2026-10-01, sintoma: ``StaffCreate.display_name`` y ``StaffUpdate.display_name``
aceptaban hasta 255 caracteres, pero ``staff.display_name`` es ``String(100)``
(la migracion ``d5ec116d06a3`` la bajo de 255 a 100). Un nombre de 101 a 255
caracteres pasaba Pydantic, Postgres lo rechazaba (``value too long``) y la API
contestaba 500, porque ``main.py`` solo mapea los SQLSTATE de concurrencia.
SQLite no aplica el largo del ``VARCHAR``, asi que la suite de integracion
daba verde: este test mira el contrato (422 en el borde), no la base.

El guardia general, que compara todos los schemas contra sus columnas, es
``tests/architecture/test_limites_de_schema_vs_columna.py``.
"""

from typing import Any

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

LIMITE = 100


def _persona(**cambios: Any) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {
        "display_name": "Ana",
        "first_name": "Ana",
        "last_name": "Perez",
        "email": "ana-limites@example.com",
    }
    cuerpo.update(cambios)
    return cuerpo


@pytest.mark.asyncio
@pytest.mark.parametrize("campo", ["display_name", "first_name", "last_name"])
async def test_el_alta_de_una_persona_acepta_el_largo_de_la_columna(
    client: AsyncClient, campo: str
) -> None:
    _, token = await register_and_login(
        client, slug="limites-alta-ok", email="limites-alta-ok@example.com"
    )
    res = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json=_persona(**{campo: "a" * LIMITE}),
    )
    assert res.status_code == 201, res.text
    assert len(res.json()[campo]) == LIMITE


@pytest.mark.asyncio
@pytest.mark.parametrize("campo", ["display_name", "first_name", "last_name"])
async def test_el_alta_de_una_persona_rechaza_mas_que_la_columna(
    client: AsyncClient, campo: str
) -> None:
    _, token = await register_and_login(
        client, slug="limites-alta-422", email="limites-alta-422@example.com"
    )
    for largo in (LIMITE + 1, 255):
        res = await client.post(
            "/staff/",
            headers=auth_headers(token),
            json=_persona(**{campo: "a" * largo}),
        )
        assert res.status_code == 422, f"{campo} de {largo}: {res.status_code}"


@pytest.mark.asyncio
async def test_el_alta_de_un_recurso_rechaza_un_nombre_mas_largo_que_la_columna(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="limites-recurso", email="limites-recurso@example.com"
    )
    ok = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={"kind": "resource", "display_name": "c" * LIMITE},
    )
    assert ok.status_code == 201, ok.text

    largo = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={"kind": "resource", "display_name": "c" * (LIMITE + 1)},
    )
    assert largo.status_code == 422, largo.text


@pytest.mark.asyncio
@pytest.mark.parametrize("campo", ["display_name", "first_name", "last_name"])
async def test_la_edicion_respeta_el_largo_de_la_columna(
    client: AsyncClient, campo: str
) -> None:
    _, token = await register_and_login(
        client, slug="limites-edicion", email="limites-edicion@example.com"
    )
    alta = await client.post("/staff/", headers=auth_headers(token), json=_persona())
    assert alta.status_code == 201, alta.text
    public_id = alta.json()["public_id"]

    ok = await client.patch(
        f"/staff/{public_id}",
        headers=auth_headers(token),
        json={campo: "b" * LIMITE},
    )
    assert ok.status_code == 200, ok.text
    assert len(ok.json()[campo]) == LIMITE

    for largo in (LIMITE + 1, 255):
        res = await client.patch(
            f"/staff/{public_id}",
            headers=auth_headers(token),
            json={campo: "b" * largo},
        )
        assert res.status_code == 422, f"{campo} de {largo}: {res.status_code}"
