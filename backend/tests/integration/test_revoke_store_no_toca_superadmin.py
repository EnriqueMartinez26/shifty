"""``revoke-store`` no corta las sesiones del superadmin.

AUD2-B3-02, 2026-09-20. Sintoma: ``revoke_user_sessions`` implementa la decision
S-15 (la cuenta del superadmin no existe para un admin de tienda) excluyendo a
los globales del WHERE, pero ``revoke_store_sessions`` -- el boton "cerrar todas
las sesiones de mi negocio" -- revocaba por ``AuthSession.store_id`` y nada mas.
Las sesiones del superadmin llevan el store_id de su tienda real, asi que el
otro admin de esa tienda podia botarlo cada vez que volviera a entrar, justo
cuando se lo necesita (es quien suspende o reactiva la tienda). Reglas 14 y 15.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

PASSWORD = "Password123!"


@pytest.mark.asyncio
async def test_el_admin_de_tienda_no_bota_al_superadmin_de_su_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token_admin = await register_and_login(
        client, slug="aud2-revoke", email="aud2-revoke@test.com"
    )
    dueno = (
        await test_session.execute(
            select(User).where(User.email == "aud2-revoke@test.com")
        )
    ).scalar_one()
    test_session.add(
        User(
            email="aud2-sa@test.com",
            hashed_password=hash_password(PASSWORD),
            first_name="Global",
            last_name="Admin",
            full_name="Global Admin",
            role=UserRole.ADMIN,
            store_id=dueno.store_id,
            is_global_admin=True,
        )
    )
    await test_session.commit()
    login = await client.post(
        "/auth/login", json={"email": "aud2-sa@test.com", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    token_sa = str(login.json()["access_token"])

    res = await client.post(
        "/auth/sessions/revoke-store", headers=auth_headers(token_admin)
    )
    assert res.status_code == 200, res.text

    viva = await client.get("/me", headers=auth_headers(token_sa))
    assert viva.status_code == 200, "el admin de tienda corto la sesion del superadmin"
    muerta = await client.get("/me", headers=auth_headers(token_admin))
    assert muerta.status_code in {401, 403}


@pytest.mark.asyncio
async def test_el_superadmin_si_corta_todas_las_de_su_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="aud2-revoke-sa", email="aud2-revoke-sa@test.com"
    )
    dueno = (
        await test_session.execute(
            select(User).where(User.email == "aud2-revoke-sa@test.com")
        )
    ).scalar_one()
    dueno.is_global_admin = True
    test_session.add(
        User(
            email="aud2-otro-sa@test.com",
            hashed_password=hash_password(PASSWORD),
            first_name="Otro",
            last_name="Global",
            full_name="Otro Global",
            role=UserRole.ADMIN,
            store_id=dueno.store_id,
            is_global_admin=True,
        )
    )
    await test_session.commit()
    otro = await client.post(
        "/auth/login", json={"email": "aud2-otro-sa@test.com", "password": PASSWORD}
    )
    token_otro = str(otro.json()["access_token"])
    login = await client.post(
        "/auth/login", json={"email": "aud2-revoke-sa@test.com", "password": PASSWORD}
    )
    token_global = str(login.json()["access_token"])

    res = await client.post(
        "/auth/sessions/revoke-store", headers=auth_headers(token_global)
    )
    assert res.status_code == 200, res.text
    muerta = await client.get("/me", headers=auth_headers(token_otro))
    assert muerta.status_code in {401, 403}
