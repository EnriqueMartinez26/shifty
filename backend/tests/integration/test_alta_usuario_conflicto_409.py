"""Un conflicto de unicidad en el alta de usuario responde 409 neutro.

Auditoria B3-12, 2026-09-16 (decision del 2026-09-18). Sintoma: el alta por
``POST /users/`` atrapaba CUALQUIER ``IntegrityError`` y respondia 400 "Ya
existe un usuario con ese email". Pero la tabla tiene mas de una restriccion
unica: un telefono de cliente repetido en la tienda viola
``uq_users_client_phone_per_store`` y el panel mostraba igual "ya existe ese
email", una causa falsa. Regla 20 de CLAUDE.md: el ``IntegrityError`` sale como
409 neutro por el handler global de ``main.py``, sin nombrar la fila ni la
columna en conflicto.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

JsonDict = dict[str, Any]
PASSWORD = "Password123!"


def _cliente(email: str, phone: str) -> JsonDict:
    return {
        "email": email,
        "first_name": "Cliente",
        "last_name": "Repetido",
        "password": PASSWORD,
        "phone": phone,
        "role": "client",
    }


def _es_409_neutro(res_json: JsonDict) -> None:
    assert res_json["error_code"] == "RESOURCE_CONFLICT", res_json
    assert "email" not in res_json["message"].lower(), res_json


@pytest.mark.asyncio
async def test_un_telefono_de_cliente_repetido_no_se_informa_como_email(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="alta-409-tel", email="alta-409-tel@test.com"
    )
    primero = await client.post(
        "/users/",
        headers=auth_headers(token),
        json=_cliente("uno@test.com", "1155550000"),
    )
    assert primero.status_code == 201, primero.text

    repetido = await client.post(
        "/users/",
        headers=auth_headers(token),
        json=_cliente("dos@test.com", "1155550000"),
    )
    assert repetido.status_code == 409, repetido.text
    _es_409_neutro(cast(JsonDict, repetido.json()))

    total = await test_session.execute(
        select(func.count()).select_from(User).where(User.phone == "1155550000")
    )
    assert total.scalar_one() == 1


@pytest.mark.asyncio
async def test_un_email_repetido_tambien_sale_como_409_neutro(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="alta-409-mail", email="alta-409-mail@test.com"
    )
    # PV-01 (2026-09-25): un cliente puede tener el email de una cuenta del
    # personal; lo que choca es el email de OTRO cliente de la misma tienda
    # (uq_users_client_email_per_store).
    primero = await client.post(
        "/users/",
        headers=auth_headers(token),
        json=_cliente("cliente-409-mail@test.com", "1166660002"),
    )
    assert primero.status_code == 201, primero.text
    repetido = await client.post(
        "/users/",
        headers=auth_headers(token),
        json=_cliente("cliente-409-mail@test.com", "1166660000"),
    )
    assert repetido.status_code == 409, repetido.text
    _es_409_neutro(cast(JsonDict, repetido.json()))

    # La sesion queda sana: la siguiente operacion del mismo admin funciona.
    otro = await client.post(
        "/users/",
        headers=auth_headers(token),
        json=_cliente("alta-409-otro@test.com", "1166660001"),
    )
    assert otro.status_code == 201, otro.text
