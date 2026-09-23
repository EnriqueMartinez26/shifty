"""Un conflicto de unicidad EDITANDO un usuario tambien es 409, no 400.

AUD2-B3-10, 2026-09-20. Sintoma: B3-12 (2026-09-18) decidio que en el alta el
``IntegrityError`` ya no se traduce -sube al handler global de ``main.py``, que
responde 409 neutro (regla 20)- porque el 400 anterior afirmaba una causa que
podia ser falsa. ``UserService.create`` lo cumple; ``UserService.update``, tres
lineas mas abajo, seguia haciendo ``raise ValueError("No se pudo actualizar el
usuario")`` y el router lo convertia en 400.

El mensaje era neutro, asi que no afirmaba una causa falsa, pero el CODIGO si:
chocar con ``uq_users_client_phone_per_store`` o con ``uq_users_email_lower`` es
un conflicto (409), no un error de la solicitud, y el front no podia
distinguirlo de una validacion. Misma decision que el alta, mismo contrato.
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
        "last_name": "Editado",
        "password": PASSWORD,
        "phone": phone,
        "role": "client",
    }


@pytest.mark.asyncio
async def test_editar_un_telefono_ya_usado_da_409_neutro(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _store, token = await register_and_login(
        client, slug="b310-edita", email="b310-edita@test.com"
    )
    primero = await client.post(
        "/users/",
        headers=auth_headers(token),
        json=_cliente("b310-a@test.com", "1155551111"),
    )
    assert primero.status_code == 201, primero.text
    segundo = await client.post(
        "/users/",
        headers=auth_headers(token),
        json=_cliente("b310-b@test.com", "1155552222"),
    )
    assert segundo.status_code == 201, segundo.text

    choque = await client.patch(
        f"/users/{segundo.json()['public_id']}",
        headers=auth_headers(token),
        json={"phone": "1155551111"},
    )
    assert choque.status_code == 409, choque.text
    cuerpo = cast(JsonDict, choque.json())
    assert cuerpo["error_code"] == "RESOURCE_CONFLICT", cuerpo
    # Neutro: no nombra la columna ni la fila en conflicto (regla 20).
    assert "phone" not in cuerpo["message"].lower(), cuerpo
    assert "telefono" not in cuerpo["message"].lower(), cuerpo

    # Y no se escribio nada: sigue habiendo un solo cliente con ese telefono.
    total = await test_session.execute(
        select(func.count()).select_from(User).where(User.phone == "1155551111")
    )
    assert total.scalar_one() == 1


@pytest.mark.asyncio
async def test_la_sesion_queda_sana_despues_del_conflicto(client: AsyncClient) -> None:
    """El rollback tiene que dejar la sesion usable, como en el alta."""
    _store, token = await register_and_login(
        client, slug="b310-sana", email="b310-sana@test.com"
    )
    uno = await client.post(
        "/users/",
        headers=auth_headers(token),
        json=_cliente("b310-c@test.com", "1166661111"),
    )
    dos = await client.post(
        "/users/",
        headers=auth_headers(token),
        json=_cliente("b310-d@test.com", "1166662222"),
    )
    assert uno.status_code == 201 and dos.status_code == 201

    choque = await client.patch(
        f"/users/{dos.json()['public_id']}",
        headers=auth_headers(token),
        json={"phone": "1166661111"},
    )
    assert choque.status_code == 409, choque.text

    despues = await client.patch(
        f"/users/{dos.json()['public_id']}",
        headers=auth_headers(token),
        json={"phone": "1166663333"},
    )
    assert despues.status_code == 200, despues.text
    assert despues.json()["phone"] == "1166663333"
