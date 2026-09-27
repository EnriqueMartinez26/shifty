"""El alta por ``POST /users/`` respeta la identidad real del login: lower(email).

Auditoria B3-01, 2026-09-16. Sintoma: con ``colision@test.com`` existente,
``POST /users/`` con ``COLISION@test.com`` respondia 201 (sin normalizar ni
chequear colision). Desde ese momento ``POST /auth/login`` con
``colision@test.com`` matcheaba dos filas con ``lower(email)`` y
``scalar_one_or_none`` levantaba MultipleResultsFound: 500 permanente para la
victima. Regla 16 de CLAUDE.md.

La garantia determinista es la base: ``CHECK (email = lower(email))``
(``ck_users_email_lower``, F1-12) rechaza un email sin normalizar y los indices
unicos hacen el resto: desde PV-01 (2026-09-25, migracion ``4b6d8f0a2c13``)
``uq_users_email_non_client`` para las cuentas que inician sesion (global) y
``uq_users_client_email_per_store`` para los clientes (por tienda); el
funcional global ``uq_users_email_lower`` se retiro ahi. La normalizacion en
``UserRepository.create`` es el camino feliz.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

PASSWORD = "Password123!"


def _payload(email: str) -> dict[str, str]:
    return {
        "email": email,
        "password": PASSWORD,
        "first_name": "Doble",
        "last_name": "Identidad",
    }


@pytest.mark.asyncio
async def test_alta_por_users_rechaza_colision_de_email_case_insensitive(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="users-colision", email="colision@test.com"
    )

    res = await client.post(
        "/users/", headers=auth_headers(token), json=_payload("COLISION@test.com")
    )
    assert res.status_code in {400, 409}, res.text

    repetidos = (
        await test_session.execute(
            select(func.count()).where(func.lower(User.email) == "colision@test.com")
        )
    ).scalar_one()
    assert repetidos == 1

    # El login de la victima sigue vivo (antes: MultipleResultsFound -> 500).
    login = await client.post(
        "/auth/login", json={"email": "colision@test.com", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text


@pytest.mark.asyncio
async def test_alta_por_users_guarda_el_email_en_minusculas(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="users-minusculas", email="dueno-minusculas@test.com"
    )

    res = await client.post(
        "/users/", headers=auth_headers(token), json=_payload("Nuevo.Staff@Test.com")
    )
    assert res.status_code == 201, res.text
    assert res.json()["email"] == "nuevo.staff@test.com"

    # Mismo criterio que staff y superadmin: la fila queda con la identidad
    # que el login usa, y ese login funciona con cualquier capitalizacion.
    login = await client.post(
        "/auth/login", json={"email": "NUEVO.STAFF@TEST.COM", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text


@pytest.mark.asyncio
async def test_la_base_frena_la_colision_aunque_el_codigo_no_normalice(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    # Simula un camino de escritura futuro que se olvide de normalizar: la
    # base, no Python, es quien rechaza la segunda fila. (En Postgres lo
    # prueba tests/postgres/test_pg_guardas_de_base.py sobre la migracion.)
    store_id, _ = await register_and_login(
        client, slug="users-indice", email="indice@test.com"
    )

    test_session.add(
        User(
            email="Indice@test.com",
            hashed_password=hash_password(PASSWORD),
            first_name="Sin",
            last_name="Normalizar",
            role=UserRole.STAFF,
            store_id=store_id,
        )
    )
    # F1-12: el CHECK rechaza la fila antes que el indice funcional.
    with pytest.raises(IntegrityError, match="ck_users_email_lower"):
        await test_session.flush()
    await test_session.rollback()
