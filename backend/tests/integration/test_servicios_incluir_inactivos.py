"""B6-06 (2026-09-18): el borrado logico de un servicio era irreversible por API.

Sintoma: ``DELETE /services/{public_id}`` apaga ``is_active`` y
``GET /services/`` solo lista activos, sin aceptar ``include_inactive``. El
panel perdia el ``public_id`` del servicio borrado y no podia enumerarlo para
reactivarlo con ``PATCH {"is_active": true}``: un borrado por error solo se
recuperaba con acceso a la base. El parametro ``only_active`` del repositorio
existia pero nadie lo ejecutaba con ``False`` (X-12 del audit: se expone, no
se borra).

Contrato: sin el parametro la respuesta es la de siempre (solo activos), que
es lo que consume el front. Ver inactivos es gestion del catalogo, asi que
queda para los mismos roles que pueden borrar/reactivar (``STORE_MANAGERS``):
un profesional recibe 403 si lo pide.
"""

from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_staff,
    register_and_login,
)


async def _crear_servicio(client: AsyncClient, token: str, nombre: str) -> str:
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": nombre, "duration_minutes": 30, "price": 1500},
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


async def _borrar_servicio(client: AsyncClient, token: str, public_id: str) -> None:
    res = await client.delete(f"/services/{public_id}", headers=auth_headers(token))
    assert res.status_code == 204, res.text


async def _ids_listados(
    client: AsyncClient, token: str, query: str = ""
) -> dict[str, bool]:
    res = await client.get(f"/services/{query}", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    return {item["public_id"]: item["is_active"] for item in res.json()}


@pytest.mark.asyncio
async def test_admin_lista_el_servicio_borrado_y_lo_reactiva(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="b6-06-admin", email="b6-06-admin@example.com"
    )
    activo = await _crear_servicio(client, token, "Corte")
    borrado = await _crear_servicio(client, token, "Color")
    await _borrar_servicio(client, token, borrado)

    # Contrato del front: sin parametro, solo activos (igual que antes).
    assert await _ids_listados(client, token) == {activo: True}
    assert await _ids_listados(client, token, "?include_inactive=false") == {
        activo: True
    }

    # Con el parametro aparece el borrado, marcado como inactivo.
    assert await _ids_listados(client, token, "?include_inactive=true") == {
        activo: True,
        borrado: False,
    }

    # Y con su public_id se reactiva por la via que ya existia.
    res = await client.patch(
        f"/services/{borrado}",
        headers=auth_headers(token),
        json={"is_active": True},
    )
    assert res.status_code == 200, res.text
    assert await _ids_listados(client, token) == {activo: True, borrado: True}


@pytest.mark.asyncio
async def test_include_inactive_no_cruza_tiendas(client: AsyncClient) -> None:
    _, token_a = await register_and_login(
        client, slug="b6-06-tienda-a", email="b6-06-a@example.com"
    )
    _, token_b = await register_and_login(
        client, slug="b6-06-tienda-b", email="b6-06-b@example.com"
    )
    borrado_a = await _crear_servicio(client, token_a, "Corte A")
    await _borrar_servicio(client, token_a, borrado_a)
    borrado_b = await _crear_servicio(client, token_b, "Corte B")
    await _borrar_servicio(client, token_b, borrado_b)

    assert await _ids_listados(client, token_a, "?include_inactive=true") == {
        borrado_a: False
    }
    assert await _ids_listados(client, token_b, "?include_inactive=true") == {
        borrado_b: False
    }


@pytest.mark.asyncio
async def test_profesional_no_ve_servicios_inactivos(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="b6-06-pro", email="b6-06-pro-admin@example.com"
    )
    activo = await _crear_servicio(client, token, "Corte")
    borrado = await _crear_servicio(client, token, "Color")
    staff_public_id = await create_staff(
        client, token, activo, email="b6-06-pro@example.com"
    )
    await _borrar_servicio(client, token, borrado)

    profesional = (
        await test_session.execute(select(User).where(User.id == staff_public_id))
    ).scalar_one()
    profesional.hashed_password = hash_password("StaffPass123!")
    await test_session.commit()
    login = await client.post(
        "/auth/login",
        json={"email": "b6-06-pro@example.com", "password": "StaffPass123!"},
    )
    assert login.status_code == 200, login.text
    token_pro = cast(str, login.json()["access_token"])

    # El listado por defecto del profesional no cambia.
    assert await _ids_listados(client, token_pro) == {activo: True}

    res = await client.get(
        "/services/?include_inactive=true", headers=auth_headers(token_pro)
    )
    assert res.status_code == 403, res.text
    assert borrado not in res.text
