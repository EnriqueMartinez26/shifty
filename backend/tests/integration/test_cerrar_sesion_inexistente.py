"""Cerrar una sesion propia que no existe responde "sesion no encontrada".

Auditoria B3-16, 2026-09-18. Sintoma: ``DELETE /auth/sessions/{id}`` con un id
inexistente (o de otro usuario) respondia 404 con ``USER_NOT_FOUND`` y el
mensaje "Usuario '<id de sesion>' no encontrado": nombraba un recurso que no
era el pedido. El 404 se conserva; lo que cambia es el recurso que se nombra.

Guarda (regla 15, sesiones): el filtro ``AuthSession.user_id == user.id`` sigue
en pie. La sesion de OTRO usuario es, para quien la pide, igual de inexistente:
mismo 404 y la sesion ajena no se revoca.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.auth.session_model import AuthSession
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

JsonDict = dict[str, Any]


@pytest.mark.asyncio
async def test_una_sesion_inexistente_se_informa_como_sesion(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="sesion-inexistente", email="sesion-inexistente@test.com"
    )

    res = await client.delete(
        "/auth/sessions/01JNOEXISTE0000000000000000", headers=auth_headers(token)
    )
    assert res.status_code == 404, res.text
    cuerpo = cast(JsonDict, res.json())
    assert cuerpo["error_code"] == "RESOURCE_NOT_FOUND", cuerpo
    assert "Usuario" not in cuerpo["message"], cuerpo
    assert "Sesión" in cuerpo["message"], cuerpo


@pytest.mark.asyncio
async def test_la_sesion_de_otro_usuario_no_se_puede_cerrar(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token_a = await register_and_login(
        client, slug="sesion-duena-a", email="sesion-duena-a@test.com"
    )
    await register_and_login(
        client, slug="sesion-duena-b", email="sesion-duena-b@test.com"
    )
    usuario_b = (
        await test_session.execute(
            select(User).where(User.email == "sesion-duena-b@test.com")
        )
    ).scalar_one()
    sesion_b = (
        await test_session.execute(
            select(AuthSession).where(AuthSession.user_id == usuario_b.id)
        )
    ).scalar_one()
    sesion_b_id = sesion_b.id

    res = await client.delete(
        f"/auth/sessions/{sesion_b_id}", headers=auth_headers(token_a)
    )
    assert res.status_code == 404, res.text
    assert cast(JsonDict, res.json())["error_code"] == "RESOURCE_NOT_FOUND"

    await test_session.refresh(sesion_b)
    assert sesion_b.revoked_at is None, "se revoco la sesion de otro usuario"
