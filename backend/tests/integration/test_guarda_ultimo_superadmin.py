"""La guarda del ultimo SuperAdmin vale en TODO camino que desactive (regla 14).

AUD2-B3-01, 2026-09-19. Sintoma: ``PATCH /users/{id}`` con ``is_active: false``
no tenia ninguna de las dos guardas que si existen al lado: ni el conteo de
superadmins activos (``superadmin/repository.py``, en ``PATCH
/superadmin/users/{id}``) ni el bloqueo de la auto-baja (``DELETE /users/{id}``).
En un solo request el ultimo superadmin podia desactivarse a si mismo: la
edicion ademas revoca sus sesiones y ``get_current_user`` rechaza a un usuario
inactivo, asi que no quedaba nadie capaz de entrar a ``/superadmin/*`` y la
plataforma se recuperaba solo con acceso al servidor
(``scripts/bootstrap_superadmin.py``).

Regla 14 de CLAUDE.md: "nunca se desactiva al ultimo activo ni uno se revoca a
si mismo". Ninguna de las tres guardas tenia test.
"""

from typing import Any, cast

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

JsonDict = dict[str, Any]
PASSWORD = "Password123!"


async def _superadmin(
    client: AsyncClient, test_session: AsyncSession, slug: str
) -> tuple[User, dict[str, str]]:
    await register_and_login(client, slug=slug, email=f"{slug}@test.com")
    usuario = (
        await test_session.execute(select(User).where(User.email == f"{slug}@test.com"))
    ).scalar_one()
    usuario.is_global_admin = True
    await test_session.commit()
    login = await client.post(
        "/auth/login", json={"email": f"{slug}@test.com", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return usuario, auth_headers(str(login.json()["access_token"]))


async def _segundo_superadmin(
    test_session: AsyncSession, store_id: str, email: str
) -> User:
    otro = User(
        email=email,
        hashed_password=hash_password(PASSWORD),
        first_name="Otro",
        last_name="Global",
        full_name="Otro Global",
        role=UserRole.ADMIN,
        store_id=store_id,
        is_global_admin=True,
    )
    test_session.add(otro)
    await test_session.commit()
    return otro


@pytest.mark.asyncio
async def test_el_unico_superadmin_no_se_desactiva_por_users(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    sa, headers = await _superadmin(client, test_session, "aud1-unico")

    res = await client.patch(
        f"/users/{sa.public_id}", headers=headers, json={"is_active": False}
    )
    assert res.status_code == 400, res.text

    await test_session.refresh(sa)
    assert sa.is_active is True, "el ultimo superadmin quedo desactivado"
    assert (await client.get("/me", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_ningun_superadmin_se_desactiva_a_si_mismo_aunque_quede_otro(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Mismo criterio que el DELETE: uno no se revoca a si mismo (regla 14)."""
    sa, headers = await _superadmin(client, test_session, "aud1-auto")
    await _segundo_superadmin(test_session, str(sa.store_id), "aud1-otro@test.com")

    res = await client.patch(
        f"/users/{sa.public_id}", headers=headers, json={"is_active": False}
    )
    assert res.status_code == 400, res.text
    await test_session.refresh(sa)
    assert sa.is_active is True


@pytest.mark.asyncio
async def test_bajar_al_ultimo_superadmin_restante_tambien_se_rechaza(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """A desactiva a B y despues queda solo: la segunda baja se rechaza."""
    sa, headers = await _superadmin(client, test_session, "aud1-dos")
    otro = await _segundo_superadmin(test_session, str(sa.store_id), "aud1-b@test.com")

    primera = await client.patch(
        f"/users/{otro.public_id}", headers=headers, json={"is_active": False}
    )
    assert primera.status_code == 200, primera.text

    # Ahora el actor es el unico activo: no puede bajarse ni por PATCH ni por DELETE.
    patch = await client.patch(
        f"/users/{sa.public_id}", headers=headers, json={"is_active": False}
    )
    assert patch.status_code == 400, patch.text
    borrado = await client.delete(f"/users/{sa.public_id}", headers=headers)
    assert borrado.status_code == 400, borrado.text
    await test_session.refresh(sa)
    assert sa.is_active is True


@pytest.mark.asyncio
async def test_el_delete_por_users_no_deja_la_plataforma_sin_superadmin(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    sa, headers = await _superadmin(client, test_session, "aud1-delete")
    otro = await _segundo_superadmin(test_session, str(sa.store_id), "aud1-c@test.com")
    await client.patch(
        f"/users/{otro.public_id}", headers=headers, json={"is_active": False}
    )

    # Con un solo superadmin activo, dar de baja a otro superadmin inactivo no
    # cambia nada; el que no se puede tocar es el ultimo ACTIVO.
    res = await client.delete(f"/users/{otro.public_id}", headers=headers)
    assert res.status_code == 204, res.text
    await test_session.refresh(sa)
    assert sa.is_active is True


@pytest.mark.asyncio
async def test_el_camino_de_superadmin_conserva_su_guarda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    sa, headers = await _superadmin(client, test_session, "aud1-panel")

    propia = await client.patch(
        f"/superadmin/users/{sa.public_id}", headers=headers, json={"is_active": False}
    )
    assert propia.status_code == 400, propia.text
    assert "SuperAdmin" in cast(JsonDict, propia.json())["message"]

    otro = await _segundo_superadmin(test_session, str(sa.store_id), "aud1-d@test.com")
    await client.patch(
        f"/users/{otro.public_id}", headers=headers, json={"is_active": False}
    )
    ultimo = await client.patch(
        f"/superadmin/users/{sa.public_id}", headers=headers, json={"is_active": False}
    )
    assert ultimo.status_code == 400, ultimo.text
    await test_session.refresh(sa)
    assert sa.is_active is True


@pytest.mark.asyncio
async def test_un_usuario_comun_se_sigue_desactivando(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="aud1-comun", email="aud1-comun@test.com"
    )
    alta = await client.post(
        "/users/",
        headers=auth_headers(token),
        json={
            "email": "aud1-staff@test.com",
            "first_name": "Pro",
            "last_name": "Fesional",
            "password": PASSWORD,
            "role": "staff",
        },
    )
    assert alta.status_code == 201, alta.text
    res = await client.patch(
        f"/users/{alta.json()['public_id']}",
        headers=auth_headers(token),
        json={"is_active": False},
    )
    assert res.status_code == 200, res.text
    assert res.json()["is_active"] is False
