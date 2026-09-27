"""``GET /superadmin/stores`` acota ``offset`` por arriba, no solo por abajo.

Auditoria B3-04, 2026-09-16. Sintoma: ``offset`` tenia ``ge=0`` sin ``le``
(regla 9 de CLAUDE.md), asi que ``?offset=9223372036854775808`` llegaba al
``.offset()`` de la query por encima del bigint de Postgres y salia 500. El
mismo incidente ya se habia cerrado en ``/users/`` (2026-09-04); este
endpoint quedo afuera.
"""

from typing import cast

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


async def _token_de_admin_global(
    client: AsyncClient, test_session: AsyncSession, *, slug: str, email: str
) -> str:
    await register_and_login(client, slug=slug, email=email)
    usuario = (
        await test_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    usuario.is_global_admin = True
    await test_session.commit()
    login = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return cast(str, login.json()["access_token"])


@pytest.mark.asyncio
async def test_listado_de_tiendas_acota_offset_por_arriba(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token = await _token_de_admin_global(
        client, test_session, slug="sa-offset", email="sa-offset@test.com"
    )
    headers = auth_headers(token)

    desborde = await client.get(
        "/superadmin/stores?offset=9223372036854775808", headers=headers
    )
    assert desborde.status_code == 422, desborde.text

    demasiado = await client.get("/superadmin/stores?offset=1000001", headers=headers)
    assert demasiado.status_code == 422, demasiado.text

    # El maximo permitido sigue funcionando (lista vacia, no error).
    tope = await client.get("/superadmin/stores?offset=1000000", headers=headers)
    assert tope.status_code == 200, tope.text
    assert tope.json() == []

    normal = await client.get("/superadmin/stores?limit=50&offset=0", headers=headers)
    assert normal.status_code == 200, normal.text
    assert len(normal.json()) == 1
