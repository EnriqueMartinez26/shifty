"""El color del portal se valida igual lo mande el dueno o el superadmin.

AUD2-B3-13, 2026-09-20. Sintoma: ``StoreUpdate.primary_color`` (panel de la
tienda) exige el patron ``^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$``, pero
``StoreCreate.primary_color`` y ``StoreGlobalUpdate.primary_color`` (superadmin)
solo ponian ``max_length=20`` y no pasaban por ninguna validacion, aunque el
mismo archivo si aplica ``reject_control_chars`` al ``name`` "porque sale al
portal publico". El valor termina en el tema del portal como valor CSS: es
texto publicado, regla 19, con la lectura que adopto B3-15.

Solo lo alcanza el superadmin y 20 caracteres acotan mucho lo que se puede
inyectar -de ahi la Baja-, pero era una asimetria gratuita entre dos schemas
del MISMO campo, y la proxima decision se toma leyendo el que este mas a mano.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.stores.model import Store
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

JsonDict = dict[str, Any]
PASSWORD = "Password123!"


async def _global_admin(
    client: AsyncClient, test_session: AsyncSession, slug: str
) -> str:
    email = f"{slug}@test.com"
    await register_and_login(client, slug=slug, email=email)
    usuario = (
        await test_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    usuario.is_global_admin = True
    await test_session.commit()
    login = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


@pytest.mark.asyncio
async def test_el_alta_de_tienda_rechaza_un_color_que_no_es_color(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token = await _global_admin(client, test_session, "b313-alta")

    res = await client.post(
        "/superadmin/stores",
        headers=auth_headers(token),
        # Corto a proposito: con 21 caracteres o mas lo frena `max_length=20` y
        # el test estaria verde por el motivo equivocado.
        json={
            "name": "Tienda Color",
            "slug": "b313-color",
            "primary_color": "url(x)",
        },
    )
    assert res.status_code == 422, res.text

    # Y no se creo nada a medias.
    creada = (
        await test_session.execute(select(Store).where(Store.slug == "b313-color"))
    ).scalar_one_or_none()
    assert creada is None


@pytest.mark.asyncio
async def test_la_edicion_global_rechaza_un_color_que_no_es_color(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token = await _global_admin(client, test_session, "b313-edita")
    alta = await client.post(
        "/superadmin/stores",
        headers=auth_headers(token),
        json={"name": "Tienda OK", "slug": "b313-ok", "primary_color": "#ABCDEF"},
    )
    assert alta.status_code == 201, alta.text
    public_id = alta.json()["public_id"]

    res = await client.patch(
        f"/superadmin/stores/{public_id}",
        headers=auth_headers(token),
        json={"primary_color": "rojo"},
    )
    assert res.status_code == 422, res.text

    # El color valido anterior sigue en pie.
    leida = await client.get(
        f"/superadmin/stores/{public_id}", headers=auth_headers(token)
    )
    assert leida.status_code == 200, leida.text
    assert leida.json()["primary_color"] == "#ABCDEF"


@pytest.mark.asyncio
async def test_los_colores_validos_siguen_pasando(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El patron no puede volverse un candado: los dos formatos siguen bien."""
    token = await _global_admin(client, test_session, "b313-validos")

    alta = await client.post(
        "/superadmin/stores",
        headers=auth_headers(token),
        json={"name": "Tienda Corta", "slug": "b313-corta", "primary_color": "#abc"},
    )
    assert alta.status_code == 201, alta.text
    assert alta.json()["primary_color"] == "#abc"

    res = await client.patch(
        f"/superadmin/stores/{alta.json()['public_id']}",
        headers=auth_headers(token),
        json={"primary_color": "#1A2B3C"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["primary_color"] == "#1A2B3C"
