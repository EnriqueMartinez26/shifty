"""Revocar el flag global pasa por la MISMA guarda que desactivar (regla 14).

AUD2-B3-12, 2026-09-20. Sintoma: ``UserAdminRepository.set_global_admin``
tenia su propia copia de la guarda del "ultimo SuperAdmin activo", con un
``SELECT count(*)`` sin lock (el "verificar y luego actuar" de la regla 4) y
sin ningun test. AUD2-B3-01 habia llevado la guarda de la DESACTIVACION a
``modules/users/guards.py`` y le habia puesto el ``FOR UPDATE``; la
REVOCACION del flag, que deja la plataforma igual de vacia de SuperAdmin,
quedo con la version vieja.

Lo que se prueba aca es la guarda viva en el camino de ``PATCH
/superadmin/users/{id}/global-admin`` (que no tenia ninguno). El lock en si
no es observable en SQLite: se afirma en ``tests/unit/
test_guarda_superadmin_toma_lock.py`` y se ejercita con una rafaga real en
``tests/postgres/test_pg_ultimo_superadmin_concurrente.py``.
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
async def test_el_ultimo_superadmin_no_se_revoca_a_si_mismo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    sa, headers = await _superadmin(client, test_session, "b312-auto")

    res = await client.patch(
        f"/superadmin/users/{sa.public_id}/global-admin",
        headers=headers,
        json={"is_global_admin": False},
    )
    assert res.status_code == 400, res.text
    assert res.json()["error_code"] == "SELF_SUPERADMIN_REVOCATION_DENIED"

    await test_session.refresh(sa)
    assert sa.is_global_admin is True, "el superadmin se revoco a si mismo"


@pytest.mark.asyncio
async def test_no_se_revoca_el_flag_del_ultimo_superadmin_activo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """A revoca a B: queda A solo. La segunda revocacion ya no puede salir."""
    sa, headers = await _superadmin(client, test_session, "b312-dos")
    otro = await _segundo_superadmin(test_session, str(sa.store_id), "b312-b@test.com")

    primera = await client.patch(
        f"/superadmin/users/{otro.public_id}/global-admin",
        headers=headers,
        json={"is_global_admin": False},
    )
    assert primera.status_code == 200, primera.text

    # Con A como unico global activo, ni el mismo A ni nadie lo puede bajar.
    segunda = await client.patch(
        f"/superadmin/users/{sa.public_id}/global-admin",
        headers=headers,
        json={"is_global_admin": False},
    )
    assert segunda.status_code == 400, segunda.text
    assert segunda.json()["error_code"] == "SELF_SUPERADMIN_REVOCATION_DENIED"

    await test_session.refresh(sa)
    await test_session.refresh(otro)
    assert sa.is_global_admin is True
    assert otro.is_global_admin is False
    assert (await client.get("/me", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_revocar_a_otro_superadmin_quedando_dos_sigue_saliendo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """La guarda no puede volverse un candado: con tres, revocar uno sale."""
    sa, headers = await _superadmin(client, test_session, "b312-tres")
    b = await _segundo_superadmin(test_session, str(sa.store_id), "b312-c@test.com")
    await _segundo_superadmin(test_session, str(sa.store_id), "b312-d@test.com")

    res = await client.patch(
        f"/superadmin/users/{b.public_id}/global-admin",
        headers=headers,
        json={"is_global_admin": False},
    )
    assert res.status_code == 200, res.text
    assert res.json()["is_global_admin"] is False
