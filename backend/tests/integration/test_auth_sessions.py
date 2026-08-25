"""Ciclo de vida de la sesion y recuperacion de contraseña.

Cubre refresh, logout, revocacion y el flujo de reset, incluida la propiedad
de que el endpoint de recuperacion no revele si un email existe.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password_reset_token
from modules.users.model import User

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


async def _login(client: AsyncClient, email: str) -> AsyncClient:
    res = await client.post(
        "/auth/login", json={"email": email, "password": "Password123!"}
    )
    assert res.status_code == 200, res.text
    return client


@pytest.mark.asyncio
async def test_refresh_renueva_la_sesion(client: AsyncClient) -> None:
    await register_and_login(client, slug="sesion-refresh", email="refresh@test.com")
    await _login(client, "refresh@test.com")

    res = await client.post("/auth/refresh")
    assert res.status_code == 200, res.text
    assert res.json()["access_token"]


@pytest.mark.asyncio
async def test_refresh_sin_sesion_es_rechazado(client: AsyncClient) -> None:
    res = await client.post("/auth/refresh")
    assert res.status_code in {401, 403}, res.text


@pytest.mark.asyncio
async def test_logout_invalida_el_refresh(client: AsyncClient) -> None:
    await register_and_login(client, slug="sesion-logout", email="logout@test.com")
    await _login(client, "logout@test.com")

    salida = await client.post("/auth/logout")
    assert salida.status_code == 204, salida.text

    reintento = await client.post("/auth/refresh")
    assert reintento.status_code in {401, 403}, "el refresh sobrevivio al logout"


@pytest.mark.asyncio
async def test_revocar_todas_las_sesiones_de_la_tienda(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="sesion-revoca", email="revoca@test.com"
    )
    await _login(client, "revoca@test.com")

    res = await client.post("/auth/sessions/revoke-store", headers=auth_headers(token))
    assert res.status_code == 200, res.text

    reintento = await client.post("/auth/refresh")
    assert reintento.status_code in {401, 403}


@pytest.mark.asyncio
async def test_forgot_password_no_revela_si_el_email_existe(
    client: AsyncClient,
) -> None:
    """Un atacante no puede enumerar cuentas por la respuesta."""
    await register_and_login(client, slug="sesion-forgot", email="forgot@test.com")

    existente = await client.post(
        "/auth/forgot-password", json={"email": "forgot@test.com"}
    )
    inexistente = await client.post(
        "/auth/forgot-password", json={"email": "nadie@test.com"}
    )

    assert existente.status_code == inexistente.status_code == 200
    assert existente.json() == inexistente.json()


@pytest.mark.asyncio
async def test_reset_password_cambia_la_credencial_y_consume_el_token(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    await register_and_login(client, slug="sesion-reset", email="reset@test.com")

    pedido = await client.post(
        "/auth/forgot-password", json={"email": "reset@test.com"}
    )
    assert pedido.status_code == 200

    # El token viaja por mail: lo recuperamos de la base para simular el clic.
    usuario = (
        await test_session.execute(select(User).where(User.email == "reset@test.com"))
    ).scalar_one()
    token_plano = "token-de-prueba-para-reset-1234567890"
    usuario.password_reset_token_hash = hash_password_reset_token(token_plano)
    usuario.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=30
    )
    await test_session.commit()

    cambio = await client.post(
        "/auth/reset-password",
        json={"token": token_plano, "new_password": "NuevaPassword456!"},
    )
    assert cambio.status_code == 200, cambio.text

    nueva = await client.post(
        "/auth/login",
        json={"email": "reset@test.com", "password": "NuevaPassword456!"},
    )
    assert nueva.status_code == 200, nueva.text

    vieja = await client.post(
        "/auth/login", json={"email": "reset@test.com", "password": "Password123!"}
    )
    assert vieja.status_code in {401, 403}, "la contraseña vieja sigue sirviendo"

    reuso = await client.post(
        "/auth/reset-password",
        json={"token": token_plano, "new_password": "OtraMas789!"},
    )
    assert reuso.status_code >= 400, "el token de reset se pudo reutilizar"


@pytest.mark.asyncio
async def test_reset_con_token_invalido_es_rechazado(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/reset-password",
        json={"token": "token-que-no-existe-000000", "new_password": "Password999!"},
    )
    assert res.status_code >= 400, res.text


@pytest.mark.asyncio
async def test_cambio_de_password_exige_la_actual(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="sesion-cambio", email="cambio@test.com"
    )

    incorrecta = await client.put(
        "/auth/change-password",
        headers=auth_headers(token),
        json={"current_password": "NoEsLaMia1!", "new_password": "Password456!"},
    )
    assert incorrecta.status_code >= 400, incorrecta.text

    correcta = await client.put(
        "/auth/change-password",
        headers=auth_headers(token),
        json={"current_password": "Password123!", "new_password": "Password456!"},
    )
    assert correcta.status_code in {200, 204}, correcta.text

    nueva = await client.post(
        "/auth/login",
        json={"email": "cambio@test.com", "password": "Password456!"},
    )
    assert nueva.status_code == 200, nueva.text
