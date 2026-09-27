"""``/staff/`` tampoco toca la cuenta del superadmin ni el acceso de otro admin.

S-15, 2026-09-19 (segundo camino). Sintoma: ``Staff.id`` es el ``User.id`` del
profesional y ``PUT/PATCH /staff/{id}`` sincroniza en el ``User`` el email, el
nombre y ``is_active``; ``DELETE /staff/{id}`` lo desactiva. Un profesional que
despues fue ascendido a admin o a superadmin conserva su ``Staff``: por ahi un
admin de tienda podia cambiarle el email de login (y tomar la cuenta con
"olvide mi contrasena") o darlo de baja, rodeando la guarda de ``/users/``.

Misma regla que en ``/users/``: la cuenta global no existe para un admin de
tienda (404) y el email de login y el estado de OTRO admin de tienda no se
cambian (403); el nombre visible, el nombre y los servicios si. El superadmin
puede todo.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _profesional_ascendido(
    client: AsyncClient,
    test_session: AsyncSession,
    slug: str,
    *,
    global_admin: bool,
) -> tuple[str, str, User]:
    """Tienda con un profesional al que despues se asciende. (token, id, user)."""
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@test.com")
    servicio = await create_service(client, token)
    staff_id = await create_staff(client, token, servicio, email=f"pro-{slug}@test.com")
    usuario = (
        await test_session.execute(select(User).where(User.id == staff_id))
    ).scalar_one()
    usuario.role = UserRole.ADMIN
    usuario.is_global_admin = global_admin
    await test_session.commit()
    return token, staff_id, usuario


@pytest.mark.asyncio
async def test_el_staff_de_un_superadmin_no_existe_para_el_admin_de_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, staff_id, usuario = await _profesional_ascendido(
        client, test_session, "s15-staff-sa", global_admin=True
    )
    headers = auth_headers(token)

    for cuerpo in (
        {"email": "atacante@test.com"},
        {"is_active": False},
        {"display_name": "Otro nombre"},
    ):
        res = await client.put(f"/staff/{staff_id}", headers=headers, json=cuerpo)
        assert res.status_code == 404, (cuerpo, res.text)
    baja = await client.delete(f"/staff/{staff_id}", headers=headers)
    assert baja.status_code == 404, baja.text

    await test_session.refresh(usuario)
    assert usuario.email == "pro-s15-staff-sa@test.com"
    assert usuario.is_active is True


@pytest.mark.asyncio
async def test_el_admin_de_tienda_no_cambia_email_ni_estado_de_otro_admin(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, staff_id, usuario = await _profesional_ascendido(
        client, test_session, "s15-staff-admin", global_admin=False
    )
    headers = auth_headers(token)

    for cuerpo in ({"email": "atacante@test.com"}, {"is_active": False}):
        res = await client.put(f"/staff/{staff_id}", headers=headers, json=cuerpo)
        assert res.status_code == 403, (cuerpo, res.text)
    baja = await client.delete(f"/staff/{staff_id}", headers=headers)
    assert baja.status_code == 403, baja.text

    await test_session.refresh(usuario)
    assert usuario.email == "pro-s15-staff-admin@test.com"
    assert usuario.is_active is True

    # Nombre visible y nombre si; reenviar su mismo email no es cambiarlo.
    ok = await client.put(
        f"/staff/{staff_id}",
        headers=headers,
        json={
            "display_name": "Coadmin Pro",
            "first_name": "Co",
            "email": "pro-s15-staff-admin@test.com",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["display_name"] == "Coadmin Pro"


@pytest.mark.asyncio
async def test_con_un_profesional_comun_nada_cambia(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="s15-staff-comun", email="s15-staff-comun@test.com"
    )
    servicio = await create_service(client, token)
    staff_id = await create_staff(client, token, servicio, email="pro-comun@test.com")
    res = await client.put(
        f"/staff/{staff_id}",
        headers=auth_headers(token),
        json={"email": "pro-comun-nuevo@test.com", "is_active": False},
    )
    assert res.status_code == 200, res.text
    usuario = (
        await test_session.execute(select(User).where(User.id == staff_id))
    ).scalar_one()
    await test_session.refresh(usuario)
    assert usuario.email == "pro-comun-nuevo@test.com"
    assert usuario.is_active is False


@pytest.mark.asyncio
async def test_el_superadmin_si_edita_el_staff_de_otro_superadmin(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, staff_id, usuario = await _profesional_ascendido(
        client, test_session, "s15-staff-global", global_admin=True
    )
    dueno = (
        await test_session.execute(
            select(User).where(User.email == "s15-staff-global@test.com")
        )
    ).scalar_one()
    dueno.is_global_admin = True
    await test_session.commit()

    res = await client.put(
        f"/staff/{staff_id}",
        headers=auth_headers(token),
        json={"email": "pro-global-nuevo@test.com"},
    )
    assert res.status_code == 200, res.text
    await test_session.refresh(usuario)
    assert usuario.email == "pro-global-nuevo@test.com"
