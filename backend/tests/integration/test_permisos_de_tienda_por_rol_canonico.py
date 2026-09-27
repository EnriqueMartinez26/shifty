"""Los permisos de ``/stores/me`` salen de ``core/roles.py``, no del enum crudo.

Auditoria B3-18, 2026-09-18. Sintoma: ``PATCH /stores/me``,
``PUT /stores/me/feature-flags`` y ``POST /stores/me/media`` decidian con
``user.role != UserRole.ADMIN``: una segunda llave de rol, la misma que
``auth/dependencies.py`` documenta como eliminada. Un superadmin
(``is_global_admin``) cuya columna ``role`` no fuera ``'admin'`` recibia 403.
Hoy no pasa solo porque ``set_global_admin`` fuerza ``role = ADMIN``: es una
invariante sostenida por otro modulo, no por esta guarda.

Guarda (regla 14, se refuerza): el personal que no es administrador sigue sin
poder cambiar la configuracion, los flags ni las imagenes de la tienda.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.unit.imagenes_sinteticas import png

# Con IHDR: desde F1-26 una imagen sin dimensiones legibles se rechaza.
_PNG = png(64, 64)


async def _escrituras(client: AsyncClient, token: str) -> dict[str, int]:
    headers = auth_headers(token)
    perfil = await client.patch(
        "/stores/me", headers=headers, json={"name": "Negocio Renombrado"}
    )
    flags = await client.put(
        "/stores/me/feature-flags", headers=headers, json={"payments": True}
    )
    imagen = await client.post(
        "/stores/me/media",
        headers=headers,
        data={"kind": "logo"},
        files={"file": ("logo.png", _PNG, "image/png")},
    )
    return {
        "perfil": perfil.status_code,
        "flags": flags.status_code,
        "imagen": imagen.status_code,
    }


async def _con_rol(
    test_session: AsyncSession, email: str, *, role: UserRole, global_admin: bool
) -> None:
    usuario = (
        await test_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    usuario.role = role
    usuario.is_global_admin = global_admin
    await test_session.commit()


@pytest.mark.asyncio
async def test_un_superadmin_con_otro_role_puede_administrar_su_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="rol-canonico-sa", email="rol-canonico-sa@test.com"
    )
    # El contexto (tienda y rol) se relee de la base en cada request (regla 1):
    # el mismo token ya actua con el rol nuevo.
    await _con_rol(
        test_session,
        "rol-canonico-sa@test.com",
        role=UserRole.STAFF,
        global_admin=True,
    )

    assert await _escrituras(client, token) == {
        "perfil": 200,
        "flags": 200,
        "imagen": 200,
    }


@pytest.mark.asyncio
async def test_el_personal_que_no_administra_sigue_sin_poder_escribir(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="rol-canonico-staff", email="rol-canonico-staff@test.com"
    )
    await _con_rol(
        test_session,
        "rol-canonico-staff@test.com",
        role=UserRole.STAFF,
        global_admin=False,
    )

    assert await _escrituras(client, token) == {
        "perfil": 403,
        "flags": 403,
        "imagen": 403,
    }
