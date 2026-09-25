"""Cambios de rol que tocan la unicidad del email de login (PV-01, revision).

2026-09-25, revision de ``fix/pv01-email-por-tienda``. Desde PV-01 el email de
un cliente es unico por tienda y el de una cuenta que inicia sesion, unico
global (``uq_users_email_non_client``); el login filtra ``role <> 'client'``.
Dos consecuencias que la revision pidio fijar:

- Un superadmin (``is_global_admin``) que pasa a ``role = client`` desaparece
  del login: nadie lo ve al buscar la cuenta y la plataforma puede quedar sin
  soporte global sin pasar por la guarda de la regla 14. Se rechaza con 409
  neutro, por ``/users/`` y por ``/superadmin/users/{id}``.
- Un cambio de rol que lleva un cliente al conjunto de cuentas de login, con
  el email de otra cuenta de login, choca con el indice: 409 neutro (regla
  20), nunca 400 ni 500. Vale para ``/users/``, para
  ``/superadmin/users/{id}`` y para ``/superadmin/users/{id}/global-admin``.
"""

from __future__ import annotations

from typing import Any

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
from tests.integration.test_superadmin import _bootstrap_global_admin

PASSWORD = "Password123!"


async def _usuario(session: AsyncSession, email: str) -> User:
    session.expire_all()
    return (
        await session.execute(
            select(User).where(User.email == email, User.role != UserRole.CLIENT)
        )
    ).scalar_one()


async def _cliente(session: AsyncSession, *, store_id: str, email: str) -> str:
    cliente = User(
        email=email,
        hashed_password=hash_password(PASSWORD),
        first_name="Cli",
        last_name="Ente",
        phone="1155550999",
        role=UserRole.CLIENT,
        store_id=store_id,
    )
    session.add(cliente)
    await session.commit()
    return str(cliente.id)


def _es_409_neutro(cuerpo: dict[str, Any], *datos: str) -> None:
    texto = str(cuerpo).lower()
    for dato in datos:
        assert dato.lower() not in texto, (dato, cuerpo)


# ------------------------------------------------ superadmin nunca es cliente
@pytest.mark.asyncio
async def test_superadmin_no_pasa_a_cliente_por_users(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers = await _bootstrap_global_admin(
        client, test_session, slug="pv01-rol-users", email="raiz-rol-users@demo.com"
    )
    yo = await _usuario(test_session, "raiz-rol-users@demo.com")

    res = await client.patch(
        f"/users/{yo.id}", headers=headers, json={"role": "client"}
    )
    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "GLOBAL_ADMIN_ROLE_LOCKED"
    assert (await _usuario(test_session, "raiz-rol-users@demo.com")).role == "admin"


@pytest.mark.asyncio
async def test_superadmin_no_pasa_a_cliente_por_superadmin(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers = await _bootstrap_global_admin(
        client, test_session, slug="pv01-rol-sa", email="raiz-rol-sa@demo.com"
    )
    otro = await _bootstrap_global_admin(
        client, test_session, slug="pv01-rol-sa-2", email="raiz-rol-sa-2@demo.com"
    )
    assert otro
    segundo = await _usuario(test_session, "raiz-rol-sa-2@demo.com")

    res = await client.patch(
        f"/superadmin/users/{segundo.id}", headers=headers, json={"role": "client"}
    )
    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "GLOBAL_ADMIN_ROLE_LOCKED"
    fila = await _usuario(test_session, "raiz-rol-sa-2@demo.com")
    assert fila.role == "admin" and fila.is_global_admin


# ------------------------------------------ cambios de rol contra el indice
@pytest.mark.asyncio
async def test_cliente_que_pasa_a_staff_con_email_de_login_ajeno_da_409(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, token = await register_and_login(
        client, slug="pv01-rol-colision", email="duena-colision@example.com"
    )
    admin = await _usuario(test_session, "duena-colision@example.com")
    # El cliente comparte el email de la duena (permitido desde PV-01).
    cliente_id = await _cliente(
        test_session, store_id=admin.store_id, email="duena-colision@example.com"
    )
    assert store

    res = await client.patch(
        f"/users/{cliente_id}", headers=auth_headers(token), json={"role": "staff"}
    )
    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "RESOURCE_CONFLICT"
    _es_409_neutro(res.json(), "duena-colision", "uq_users")


@pytest.mark.asyncio
async def test_superadmin_edita_rol_con_colision_de_email_da_409_neutro(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers = await _bootstrap_global_admin(
        client, test_session, slug="pv01-rol-sa-col", email="raiz-sa-col@demo.com"
    )
    raiz = await _usuario(test_session, "raiz-sa-col@demo.com")
    cliente_id = await _cliente(
        test_session, store_id=raiz.store_id, email="raiz-sa-col@demo.com"
    )

    res = await client.patch(
        f"/superadmin/users/{cliente_id}", headers=headers, json={"role": "staff"}
    )
    # Antes: 400 "No se pudo actualizar el usuario" (el repo tragaba la
    # IntegrityError). Regla 20: 409 neutro.
    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "RESOURCE_CONFLICT"
    _es_409_neutro(res.json(), "raiz-sa-col", "uq_users")


@pytest.mark.asyncio
async def test_promover_a_global_un_cliente_con_email_de_login_da_409(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers = await _bootstrap_global_admin(
        client, test_session, slug="pv01-rol-promo", email="raiz-promo@demo.com"
    )
    raiz = await _usuario(test_session, "raiz-promo@demo.com")
    cliente_id = await _cliente(
        test_session, store_id=raiz.store_id, email="raiz-promo@demo.com"
    )

    res = await client.patch(
        f"/superadmin/users/{cliente_id}/global-admin",
        headers=headers,
        json={"is_global_admin": True},
    )
    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "RESOURCE_CONFLICT"
    _es_409_neutro(res.json(), "raiz-promo", "uq_users")
    test_session.expire_all()
    fila = await test_session.get(User, cliente_id)
    assert fila is not None
    assert fila.role == "client" and not fila.is_global_admin
