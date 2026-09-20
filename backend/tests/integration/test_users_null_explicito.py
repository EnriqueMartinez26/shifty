"""``PATCH /users/{id}`` con ``null`` borra el campo, no lo ignora.

AUD2-B3-08, 2026-09-20. Sintoma: B3-19 (2026-09-18) resolvio el null explicito
SOLO en ``superadmin`` (``_apply_patch`` mira la nulabilidad real de la columna
y borra si admite NULL). ``UserRepository.update`` se quedo con el patron viejo
-- ``if value is not None: setattr(...)`` -- y el router encima le pasaba
``data.model_dump()`` SIN ``exclude_unset``, asi que "no vino" y "vino null"
eran indistinguibles.

Resultado: desde el panel de la tienda no se podia borrar el telefono de un
usuario (``{"phone": null}`` devolvia 200 sin cambiar nada) y si se podia desde
``/superadmin/users/{id}``, que lo prueba
``tests/integration/test_superadmin_null_explicito.py``. El mismo PATCH mentia
en un router y decia la verdad en el de al lado.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

PASSWORD = "Password123!"


async def _alta(client: AsyncClient, token: str, email: str) -> str:
    res = await client.post(
        "/users/",
        headers=auth_headers(token),
        json={
            "email": email,
            "first_name": "Pro",
            "last_name": "Fesional",
            "phone": "1122334455",
            "password": PASSWORD,
            "role": "staff",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["phone"] == "1122334455"
    return str(res.json()["public_id"])


@pytest.mark.asyncio
async def test_un_null_explicito_borra_el_telefono(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _store, token = await register_and_login(
        client, slug="b308-null", email="b308-null@test.com"
    )
    public_id = await _alta(client, token, "b308-objetivo@test.com")

    res = await client.patch(
        f"/users/{public_id}", headers=auth_headers(token), json={"phone": None}
    )
    assert res.status_code == 200, res.text
    assert res.json()["phone"] is None, "el null explicito se ignoro"

    # Y quedo borrado en la base, no solo en la respuesta.
    fila = (
        await test_session.execute(
            select(User).where(User.email == "b308-objetivo@test.com")
        )
    ).scalar_one()
    await test_session.refresh(fila)
    assert fila.phone is None


@pytest.mark.asyncio
async def test_lo_que_no_se_manda_no_se_toca(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El contrario del anterior: sin ``exclude_unset`` esto tambien mentia."""
    _store, token = await register_and_login(
        client, slug="b308-intacto", email="b308-intacto@test.com"
    )
    public_id = await _alta(client, token, "b308-otro@test.com")

    res = await client.patch(
        f"/users/{public_id}",
        headers=auth_headers(token),
        json={"first_name": "Nuevo"},
    )
    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert cuerpo["first_name"] == "Nuevo"
    assert cuerpo["phone"] == "1122334455", "una edicion de nombre borro el telefono"
    assert cuerpo["last_name"] == "Fesional"
    assert cuerpo["role"] == "staff"


@pytest.mark.asyncio
async def test_un_null_en_columna_not_null_se_sigue_ignorando(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """``role`` e ``is_active`` son NOT NULL: un null no puede llegar al INSERT.

    Mismo criterio que ``_apply_patch`` en superadmin: se ignora en vez de
    terminar en un 409 que el usuario no puede interpretar.
    """
    _store, token = await register_and_login(
        client, slug="b308-notnull", email="b308-notnull@test.com"
    )
    public_id = await _alta(client, token, "b308-nn@test.com")

    res = await client.patch(
        f"/users/{public_id}",
        headers=auth_headers(token),
        json={"role": None, "is_active": None},
    )
    assert res.status_code == 200, res.text
    assert res.json()["role"] == "staff"
    assert res.json()["is_active"] is True
