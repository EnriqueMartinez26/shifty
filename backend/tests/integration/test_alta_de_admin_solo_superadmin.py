"""Un admin de tienda no crea ni asciende a otro admin: eso es del superadmin.

Auditoria B3-02, 2026-09-16 (decision del 2026-09-18). Sintoma:
``POST /users/`` y ``PATCH /users/{id}`` aceptaban ``role: "admin"`` desde
cualquier admin de tienda (la puerta era ``get_current_admin``), asi que el
dueno podia dar de alta o ascender a otro administrador -- incluso a un
``client``, que dejaba de ser rechazado por el login y entraba al panel --
sin pasar por ``/superadmin/stores/{id}/admins``. Contradice la regla 16 de
CLAUDE.md: el alta de admins es exclusiva del superadmin.

Lo que sigue permitido: el admin de tienda da de alta y edita roles no-admin,
y edita a un admin existente sin cambiarle el rol (el formulario del panel
reenvia el ``role`` actual en cada edicion). El superadmin puede todo.

Regla 15: el cambio de rol que si se permite sigue revocando las sesiones del
usuario editado.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

JsonDict = dict[str, Any]
PASSWORD = "Password123!"


def _alta(email: str, role: str) -> JsonDict:
    return {
        "email": email,
        "first_name": "Nueva",
        "last_name": "Persona",
        "password": PASSWORD,
        "role": role,
    }


async def _crear(client: AsyncClient, token: str, email: str, role: str) -> JsonDict:
    res = await client.post(
        "/users/", headers=auth_headers(token), json=_alta(email, role)
    )
    assert res.status_code == 201, res.text
    return cast(JsonDict, res.json())


async def _cantidad(test_session: AsyncSession, email: str) -> int:
    total = await test_session.execute(
        select(func.count()).select_from(User).where(User.email == email)
    )
    return int(total.scalar_one())


@pytest.mark.asyncio
async def test_el_admin_de_tienda_no_da_de_alta_a_otro_admin(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="alta-admin", email="alta-admin@test.com"
    )

    res = await client.post(
        "/users/", headers=auth_headers(token), json=_alta("socio@test.com", "admin")
    )
    assert res.status_code == 403, res.text
    assert await _cantidad(test_session, "socio@test.com") == 0


@pytest.mark.asyncio
async def test_el_admin_de_tienda_no_asciende_a_admin(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="ascenso-admin", email="ascenso-admin@test.com"
    )
    for email, role in (("prof@test.com", "staff"), ("cli@test.com", "client")):
        creado = await _crear(client, token, email, role)
        res = await client.patch(
            f"/users/{creado['public_id']}",
            headers=auth_headers(token),
            json={"role": "admin"},
        )
        assert res.status_code == 403, res.text
        usuario = (
            await test_session.execute(select(User).where(User.email == email))
        ).scalar_one()
        await test_session.refresh(usuario)
        assert usuario.role == UserRole(role), "el ascenso rechazado cambio el rol"


@pytest.mark.asyncio
async def test_el_admin_de_tienda_sigue_gestionando_roles_no_admin(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="roles-no-admin", email="roles-no-admin@test.com"
    )
    for email, role in (
        ("staff-ok@test.com", "staff"),
        ("recepcion-ok@test.com", "receptionist"),
        ("cliente-ok@test.com", "client"),
    ):
        assert (await _crear(client, token, email, role))["role"] == role

    # Editar a un admin existente reenviando su mismo rol (lo que hace el
    # formulario del panel) no es un ascenso y sigue funcionando.
    dueno = (
        await test_session.execute(
            select(User).where(User.email == "roles-no-admin@test.com")
        )
    ).scalar_one()
    otro_admin = User(
        email="coadmin@test.com",
        hashed_password="x",
        first_name="Co",
        last_name="Admin",
        full_name="Co Admin",
        role=UserRole.ADMIN,
        store_id=dueno.store_id,
    )
    test_session.add(otro_admin)
    await test_session.commit()
    res = await client.patch(
        f"/users/{otro_admin.public_id}",
        headers=auth_headers(token),
        json={"role": "admin", "phone": "1122334455"},
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_el_cambio_de_rol_permitido_sigue_revocando_sesiones(
    client: AsyncClient,
) -> None:
    """Regla 15: staff -> recepcion corta las sesiones vivas del editado."""
    _, token = await register_and_login(
        client, slug="rol-revoca", email="rol-revoca@test.com"
    )
    creado = await _crear(client, token, "staff-revoca@test.com", "staff")
    login = await client.post(
        "/auth/login", json={"email": "staff-revoca@test.com", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    token_staff = str(login.json()["access_token"])
    assert (
        await client.get("/me", headers=auth_headers(token_staff))
    ).status_code == 200

    res = await client.patch(
        f"/users/{creado['public_id']}",
        headers=auth_headers(token),
        json={"role": "receptionist"},
    )
    assert res.status_code == 200, res.text
    muerto = await client.get("/me", headers=auth_headers(token_staff))
    assert muerto.status_code in {401, 403}, "el cambio de rol no revoco la sesion"


@pytest.mark.asyncio
async def test_el_superadmin_si_da_de_alta_y_asciende_admins(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="sa-admins", email="sa-admins@test.com"
    )
    superadmin = (
        await test_session.execute(
            select(User).where(User.email == "sa-admins@test.com")
        )
    ).scalar_one()
    superadmin.is_global_admin = True
    await test_session.commit()

    alta = await _crear(client, token, "admin-por-sa@test.com", "admin")
    assert alta["role"] == "admin"

    staff = await _crear(client, token, "staff-a-admin@test.com", "staff")
    ascenso = await client.patch(
        f"/users/{staff['public_id']}",
        headers=auth_headers(token),
        json={"role": "admin"},
    )
    assert ascenso.status_code == 200, ascenso.text
    assert ascenso.json()["role"] == "admin"
