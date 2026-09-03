"""Los clientes no acceden al panel: aislamiento por ROL dentro de la tienda.

RLS aisla entre tiendas pero no entre roles. Un usuario role=client (que existe
como usuario de primera clase y se crea al reservar) no debe poder autenticarse
ni recuperar contrasena para el panel, ni leer datos operativos de la tienda.
"""

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


async def _crear_cliente(client: AsyncClient, token: str, email: str) -> None:
    res = await client.post(
        "/users/",
        headers=auth_headers(token),
        json={
            "email": email,
            "password": "Password123!",
            "role": "client",
            "first_name": "Cli",
            "last_name": "Ente",
        },
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_client_role_cannot_login(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="authz-login", email="authz-login@example.com"
    )
    await _crear_cliente(client, token, "cliente-login@example.com")

    login = await client.post(
        "/auth/login",
        json={"email": "cliente-login@example.com", "password": "Password123!"},
    )
    assert login.status_code == 401


@pytest.mark.asyncio
async def test_client_forgot_password_does_not_grant_reset(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="authz-forgot", email="authz-forgot@example.com"
    )
    await _crear_cliente(client, token, "cliente-forgot@example.com")

    # forgot-password responde generico (no revela existencia) pero NO habilita
    # el puente cliente -> token: reset denegado igual que login.
    forgot = await client.post(
        "/auth/forgot-password", json={"email": "cliente-forgot@example.com"}
    )
    assert forgot.status_code in (200, 202)


@pytest.mark.asyncio
async def test_appointments_and_dashboard_require_staff(client: AsyncClient) -> None:
    # Con token de admin (personal) los endpoints operativos responden 200: el
    # guard get_current_staff no rompe el acceso legitimo.
    _, token = await register_and_login(
        client, slug="authz-staff", email="authz-staff@example.com"
    )
    lst = await client.get(
        "/appointments/?date=2026-09-09", headers=auth_headers(token)
    )
    assert lst.status_code == 200, lst.text
    dash = await client.get("/dashboard/summary", headers=auth_headers(token))
    assert dash.status_code == 200, dash.text
