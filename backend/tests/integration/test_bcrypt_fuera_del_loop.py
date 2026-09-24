"""bcrypt no corre en el hilo del event loop en las altas y cambios de clave.

2026-09-24, F1-06 (R8-03): ``POST /users``, ``PATCH /users`` con clave y los
dos caminos del superadmin (alta de admin y ``PATCH /superadmin/users`` con
clave, este ultimo bajo ``FOR UPDATE``) llamaban a ``hash_password`` sincrono
dentro del ``async def``: ~0,25 s de CPU con el loop congelado para TODOS los
requests del proceso. ``POST /staff`` ademas hasheaba un ULID al azar para una
cuenta que nace sin clave usable.

Se observa en que hilo corre cada hash: el loop de los tests corre en el hilo
principal, el executor de ``core.security`` no. Para ``/staff`` no tiene que
haber ningun hash: usa el hash inutilizable precalculado, como los clientes
del portal.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import core.security as security
import modules.staff.repository as staff_repository
import modules.superadmin.repository as superadmin_repository
import modules.users.repository as users_repository
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    register_and_login,
)

PASSWORD = "Password123!Largo"


def _registrar_hilos(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Devuelve una lista con ``True`` por cada hash hecho en el hilo del loop."""
    en_el_loop: list[bool] = []
    original = security.hash_password

    def registrar(password: str) -> str:
        en_el_loop.append(threading.current_thread() is threading.main_thread())
        return original(password)

    monkeypatch.setattr(security, "hash_password", registrar)
    for modulo in (users_repository, superadmin_repository, staff_repository):
        if hasattr(modulo, "hash_password"):
            monkeypatch.setattr(modulo, "hash_password", registrar)
    return en_el_loop


async def _hacer_superadmin(test_session: AsyncSession, email: str) -> None:
    usuario = (
        await test_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    usuario.is_global_admin = True
    await test_session.commit()


@pytest.mark.asyncio
async def test_alta_y_cambio_de_clave_de_usuario_no_hashean_en_el_loop(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, token = await register_and_login(
        client, slug="bcrypt-users", email="bcrypt-users@test.com"
    )
    en_el_loop = _registrar_hilos(monkeypatch)

    alta = await client.post(
        "/users/",
        headers=auth_headers(token),
        json={
            "email": "bcrypt-staff@test.com",
            "first_name": "Nueva",
            "last_name": "Persona",
            "password": PASSWORD,
            "role": "staff",
        },
    )
    assert alta.status_code == 201, alta.text
    cambio = await client.patch(
        f"/users/{alta.json()['public_id']}",
        headers=auth_headers(token),
        json={"password": PASSWORD + "2"},
    )
    assert cambio.status_code == 200, cambio.text

    assert len(en_el_loop) == 2, en_el_loop
    assert not any(en_el_loop), "bcrypt corrio en el hilo del event loop"


@pytest.mark.asyncio
async def test_el_superadmin_no_hashea_en_el_loop(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, token = await register_and_login(
        client, slug="bcrypt-sa", email="bcrypt-sa@test.com"
    )
    await _hacer_superadmin(test_session, "bcrypt-sa@test.com")
    en_el_loop = _registrar_hilos(monkeypatch)

    alta = await client.post(
        f"/superadmin/stores/{store}/admins",
        headers=auth_headers(token),
        json={
            "email": "bcrypt-admin@test.com",
            "password": PASSWORD,
            "first_name": "Admin",
            "last_name": "Nuevo",
        },
    )
    assert alta.status_code == 201, alta.text
    cambio = await client.patch(
        f"/superadmin/users/{alta.json()['public_id']}",
        headers=auth_headers(token),
        json={"password": PASSWORD + "2"},
    )
    assert cambio.status_code == 200, cambio.text

    assert len(en_el_loop) == 2, en_el_loop
    assert not any(en_el_loop), "bcrypt corrio en el hilo del event loop"


@pytest.mark.asyncio
async def test_el_alta_de_staff_no_hashea_nada(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, token = await register_and_login(
        client, slug="bcrypt-pro", email="bcrypt-pro@test.com"
    )
    servicio = await create_service(client, token)
    en_el_loop = _registrar_hilos(monkeypatch)

    res = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": "Pro",
            "first_name": "Pro",
            "last_name": "Bcrypt",
            "email": "pro-bcrypt@test.com",
            "service_ids": [servicio],
        },
    )
    assert res.status_code == 201, res.text
    assert en_el_loop == [], "el alta de staff hasheo una clave al azar"

    usuario: Any = (
        await test_session.execute(
            select(User).where(User.email == "pro-bcrypt@test.com")
        )
    ).scalar_one()
    # Sigue siendo un hash bcrypt valido que no verifica contra nada tipeable.
    assert usuario.hashed_password.startswith("$2")
    assert not security.verify_password("", usuario.hashed_password)
