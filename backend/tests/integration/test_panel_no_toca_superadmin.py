"""El panel de usuarios de una tienda no toca al superadmin ni al acceso de otro admin.

S-15, 2026-09-19 (revision V-diff de B3-02). Sintoma: ``PATCH /users/{id}`` dejaba
que un admin de tienda le fijara ``password``, ``is_active`` o ``role`` a
cualquier usuario de su tienda: ``get_by_public_id`` solo filtraba por
``store_id`` y ``UserRepository.update`` no miraba ``is_global_admin``. El dueno
de la tienda donde vive la cuenta del superadmin podia cambiarle la clave y
tomar la cuenta global. Reglas 14 y 16 de CLAUDE.md.

Decision: para un admin de tienda, un usuario con ``is_global_admin`` no existe
(404 neutro en detalle, edicion, baja y revocacion de sesiones; no aparece en
el listado), y no puede cambiar ``password``, ``is_active`` ni ``role`` de OTRO
admin de tienda (403); si puede editar sus datos de contacto. El superadmin
puede todo. Regla 15: lo que se sigue permitiendo y cambia credenciales sigue
revocando sesiones.
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
CLAVE_NUEVA = "OtraClaveSegura456"


async def _usuario(
    test_session: AsyncSession, email: str, store_id: str, *, global_admin: bool
) -> User:
    usuario = User(
        email=email,
        hashed_password=hash_password(PASSWORD),
        first_name="Otro",
        last_name="Admin",
        full_name="Otro Admin",
        role=UserRole.ADMIN,
        store_id=store_id,
        is_global_admin=global_admin,
    )
    test_session.add(usuario)
    await test_session.commit()
    return usuario


async def _tienda(
    client: AsyncClient, test_session: AsyncSession, slug: str
) -> tuple[str, str]:
    """Devuelve (token del dueno, store_id)."""
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@test.com")
    dueno = (
        await test_session.execute(select(User).where(User.email == f"{slug}@test.com"))
    ).scalar_one()
    return token, str(dueno.store_id)


async def _login(client: AsyncClient, email: str, password: str = PASSWORD) -> int:
    res = await client.post("/auth/login", json={"email": email, "password": password})
    return res.status_code


@pytest.mark.asyncio
async def test_el_superadmin_no_existe_para_el_admin_de_su_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, store_id = await _tienda(client, test_session, "s15-oculto")
    sa = await _usuario(test_session, "s15-sa@test.com", store_id, global_admin=True)
    headers = auth_headers(token)
    ruta = f"/users/{sa.public_id}"

    listado = await client.get("/users/?include_inactive=true", headers=headers)
    assert listado.status_code == 200, listado.text
    ids = [u["public_id"] for u in cast(list[JsonDict], listado.json())]
    assert sa.public_id not in ids, "el superadmin aparece en el listado de la tienda"

    assert (await client.get(ruta, headers=headers)).status_code == 404
    for cuerpo in ({"password": CLAVE_NUEVA}, {"is_active": False}, {"phone": "1"}):
        res = await client.patch(ruta, headers=headers, json=cuerpo)
        assert res.status_code == 404, (cuerpo, res.text)
    assert (await client.delete(ruta, headers=headers)).status_code == 404
    revocar = await client.post(
        f"/auth/sessions/revoke-user/{sa.public_id}", headers=headers
    )
    assert revocar.status_code == 404, revocar.text

    # La cuenta global sigue intacta: entra con su clave de siempre.
    assert await _login(client, "s15-sa@test.com") == 200
    assert await _login(client, "s15-sa@test.com", CLAVE_NUEVA) == 401


@pytest.mark.asyncio
async def test_el_admin_de_tienda_no_cambia_el_acceso_de_otro_admin(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, store_id = await _tienda(client, test_session, "s15-coadmin")
    otro = await _usuario(
        test_session, "s15-otro@test.com", store_id, global_admin=False
    )
    headers = auth_headers(token)
    ruta = f"/users/{otro.public_id}"

    for cuerpo in (
        {"password": CLAVE_NUEVA},
        {"is_active": False},
        {"role": "staff"},
    ):
        res = await client.patch(ruta, headers=headers, json=cuerpo)
        assert res.status_code == 403, (cuerpo, res.text)
    baja = await client.delete(ruta, headers=headers)
    assert baja.status_code == 403, baja.text

    await test_session.refresh(otro)
    assert otro.is_active is True
    assert otro.role == UserRole.ADMIN
    assert await _login(client, "s15-otro@test.com") == 200

    # Sus datos de contacto si se editan (y reenviar su mismo rol no es cambiarlo).
    contacto = await client.patch(
        ruta,
        headers=headers,
        json={"phone": "1122334455", "first_name": "Coadmin", "role": "admin"},
    )
    assert contacto.status_code == 200, contacto.text
    assert contacto.json()["phone"] == "1122334455"


@pytest.mark.asyncio
async def test_el_admin_de_tienda_sigue_gestionando_al_personal(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El bloqueo es solo sobre otros admins: con el personal nada cambia, y
    la clave impuesta sigue revocando las sesiones del editado (regla 15)."""
    token, _ = await _tienda(client, test_session, "s15-personal")
    headers = auth_headers(token)
    alta = await client.post(
        "/users/",
        headers=headers,
        json={
            "email": "s15-staff@test.com",
            "first_name": "Pro",
            "last_name": "Fesional",
            "password": PASSWORD,
            "role": "staff",
        },
    )
    assert alta.status_code == 201, alta.text
    login = await client.post(
        "/auth/login", json={"email": "s15-staff@test.com", "password": PASSWORD}
    )
    token_staff = str(login.json()["access_token"])

    res = await client.patch(
        f"/users/{alta.json()['public_id']}",
        headers=headers,
        json={"password": CLAVE_NUEVA},
    )
    assert res.status_code == 200, res.text
    muerto = await client.get("/me", headers=auth_headers(token_staff))
    assert muerto.status_code in {401, 403}
    assert await _login(client, "s15-staff@test.com", CLAVE_NUEVA) == 200


@pytest.mark.asyncio
async def test_el_superadmin_si_puede_todo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, store_id = await _tienda(client, test_session, "s15-global")
    dueno = (
        await test_session.execute(
            select(User).where(User.email == "s15-global@test.com")
        )
    ).scalar_one()
    dueno.is_global_admin = True
    await test_session.commit()
    otro_sa = await _usuario(
        test_session, "s15-otro-sa@test.com", store_id, global_admin=True
    )
    coadmin = await _usuario(
        test_session, "s15-co@test.com", store_id, global_admin=False
    )
    headers = auth_headers(token)

    listado = await client.get("/users/", headers=headers)
    ids = [u["public_id"] for u in cast(list[JsonDict], listado.json())]
    assert otro_sa.public_id in ids
    assert (
        await client.get(f"/users/{otro_sa.public_id}", headers=headers)
    ).status_code == 200

    res = await client.patch(
        f"/users/{coadmin.public_id}",
        headers=headers,
        json={"password": CLAVE_NUEVA, "role": "staff"},
    )
    assert res.status_code == 200, res.text
    assert await _login(client, "s15-co@test.com", CLAVE_NUEVA) == 200
