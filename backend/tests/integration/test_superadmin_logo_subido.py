"""El superadmin edita el logo con la misma regla que ``/stores/me`` (F1-30).

2026-09-24, revision de F1-28/F1-30: ``PATCH /superadmin/stores/{id}``
validaba ``logo_url`` solo como http(s). Con el logo subido (relativo antes
de F1-28) el formulario del superadmin devolvia 422 al reenviarlo, y vaciarlo
dejaba la fila huerfana en ``store_media``. Ahora: la misma imagen por id se
conserva, otra URL de medios es 422 y desvincular borra la fila.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from modules.stores.model import Store, StoreMedia
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.unit.imagenes_sinteticas import png


async def _tienda_con_logo_y_superadmin(
    client: AsyncClient, db: AsyncSession, slug: str
) -> tuple[str, dict[str, str], dict[str, object]]:
    email = f"{slug}@example.com"
    store_public_id, token = await register_and_login(client, slug=slug, email=email)
    subida = await client.post(
        "/stores/me/media",
        headers=auth_headers(token),
        data={"kind": "logo"},
        files={"file": ("logo.png", png(64, 64), "image/png")},
    )
    assert subida.status_code == 200, subida.text
    admin = (await db.execute(select(User).where(User.email == email))).scalar_one()
    admin.is_global_admin = True
    await db.commit()
    login = await client.post(
        "/auth/login", json={"email": email, "password": "Password123!"}
    )
    assert login.status_code == 200, login.text
    return store_public_id, auth_headers(login.json()["access_token"]), subida.json()


async def _filas(db: AsyncSession, store_public_id: str) -> list[str]:
    result = await db.execute(
        select(StoreMedia.id)
        .join(Store, Store.id == StoreMedia.store_id)
        .where(Store.public_id == store_public_id)
    )
    return [str(fila) for fila in result.scalars()]


@pytest.mark.asyncio
async def test_reenviar_el_logo_subido_lo_conserva(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda, headers, logo = await _tienda_con_logo_y_superadmin(
        client, test_session, "sa-logo-igual"
    )
    for forma in (logo["url"], f"/api/stores/media/{logo['media_id']}"):
        res = await client.patch(
            f"/superadmin/stores/{tienda}", headers=headers, json={"logo_url": forma}
        )
        assert res.status_code == 200, res.text
        assert res.json()["logo_url"] == logo["url"]
    assert await _filas(test_session, tienda) == [str(logo["media_id"])]


@pytest.mark.asyncio
async def test_enlazar_otra_imagen_subida_es_422(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda, headers, _ = await _tienda_con_logo_y_superadmin(
        client, test_session, "sa-logo-ajeno"
    )
    ajena = f"{settings.PUBLIC_API_URL}/stores/media/01JZZZZZZZZZZZZZZZZZZZZZZZ"
    res = await client.patch(
        f"/superadmin/stores/{tienda}", headers=headers, json={"logo_url": ajena}
    )
    assert res.status_code == 422, res.text

    alta = await client.post(
        "/superadmin/stores",
        headers=headers,
        json={"name": "Nueva", "slug": "sa-logo-alta", "logo_url": ajena},
    )
    assert alta.status_code == 422, alta.text


@pytest.mark.asyncio
@pytest.mark.parametrize("nuevo", [None, "https://cdn.example.com/logo.png"])
async def test_desvincular_el_logo_borra_la_fila(
    client: AsyncClient, test_session: AsyncSession, nuevo: str | None
) -> None:
    slug = f"sa-logo-unlink-{'null' if nuevo is None else 'url'}"
    tienda, headers, logo = await _tienda_con_logo_y_superadmin(
        client, test_session, slug
    )
    res = await client.patch(
        f"/superadmin/stores/{tienda}", headers=headers, json={"logo_url": nuevo}
    )
    assert res.status_code == 200, res.text
    assert res.json()["logo_url"] == nuevo
    assert (await client.get(f"/stores/media/{logo['media_id']}")).status_code == 404
    assert await _filas(test_session, tienda) == []
