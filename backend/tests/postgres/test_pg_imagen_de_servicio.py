"""Imagen de servicio en ``store_media`` contra Postgres real (F1-28).

2026-09-24. SQLite no corre la migracion ``e7a9c1d3f5b8``: aca se prueba que
la base sostiene lo que el codigo supone (un ``kind`` valido, ``service_id``
si y solo si es imagen de servicio, una imagen por servicio) y que la subida,
el servido y el borrado funcionan como ``shifty_app`` bajo RLS.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    create_service,
)
from tests.postgres.conftest import auth_headers, register_and_login
from tests.unit.imagenes_sinteticas import jpeg, png

pytestmark = pytest.mark.postgres

_FOTO = jpeg(1061, 1460)


async def _ids(owner_engine: AsyncEngine, servicio: str) -> tuple[str, str]:
    async with owner_engine.connect() as conn:
        fila = (
            await conn.execute(
                text("select id, store_id from services where public_id = :p"),
                {"p": servicio},
            )
        ).one()
    return str(fila.id), str(fila.store_id)


async def _insertar(
    owner_engine: AsyncEngine, store_id: str, kind: str, service_id: str | None
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "insert into store_media (id, store_id, kind, service_id, "
                "content_type, byte_size, data, created_at, updated_at, is_active) "
                "values (gen_random_uuid()::text, :store, :kind, :svc, 'image/png', "
                "1, '\\x00', now(), now(), true)"
            ),
            {"store": store_id, "kind": kind, "svc": service_id},
        )


@pytest.mark.asyncio
async def test_la_base_sostiene_el_tipo_y_el_vinculo_con_el_servicio(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    _, token = await register_and_login(
        client, app_sessions, slug="pg-img-ck", email="pg-img-ck@example.com"
    )
    servicio = await create_service(client, token)
    service_id, store_id = await _ids(owner_engine, servicio)

    for kind, svc in (
        ("banner", None),  # ck_store_media_kind
        ("service", None),  # ck_store_media_service_id
        ("logo", service_id),  # idem, al reves
    ):
        with pytest.raises(IntegrityError):
            await _insertar(owner_engine, store_id, kind, svc)

    await _insertar(owner_engine, store_id, "service", service_id)
    with pytest.raises(IntegrityError, match="uq_store_media_service_id"):
        await _insertar(owner_engine, store_id, "service", service_id)


@pytest.mark.asyncio
async def test_subir_reemplazar_servir_y_borrar_como_shifty_app(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store_public_id, token = await register_and_login(
        client, app_sessions, slug="pg-img-flujo", email="pg-img-flujo@example.com"
    )
    servicio = await create_service(client, token)

    primera = await client.post(
        f"/services/{servicio}/image",
        headers=auth_headers(token),
        files={"file": ("foto.jpg", _FOTO, "image/jpeg")},
    )
    assert primera.status_code == 200, primera.text
    segunda = await client.post(
        f"/services/{servicio}/image",
        headers=auth_headers(token),
        files={"file": ("foto.png", png(800, 600), "image/png")},
    )
    assert segunda.status_code == 200, segunda.text
    # La URL es absoluta ({PUBLIC_API_URL}/stores/media/{id}): el id es el
    # ultimo segmento.
    vieja = primera.json()["image_url"].rsplit("/", 1)[-1]
    url = segunda.json()["image_url"]
    nueva = url.rsplit("/", 1)[-1]

    assert (await client.get(f"/stores/media/{vieja}")).status_code == 404
    servida = await client.get(f"/stores/media/{nueva}")
    assert servida.status_code == 200
    assert servida.headers["etag"] == f'"{nueva}"'
    catalogo = await client.get(
        "/public/services", params={"store_public_id": store_public_id}
    )
    assert [s["image_url"] for s in catalogo.json()] == [url]

    borrada = await client.delete(
        f"/services/{servicio}/image", headers=auth_headers(token)
    )
    assert borrada.status_code == 200, borrada.text
    assert borrada.json()["image_url"] is None
    async with owner_engine.connect() as conn:
        quedan = (
            await conn.execute(text("select count(*) from store_media"))
        ).scalar_one()
    assert quedan == 0


@pytest.mark.asyncio
async def test_borrar_el_servicio_de_verdad_se_lleva_su_imagen(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    _, token = await register_and_login(
        client, app_sessions, slug="pg-img-cascada", email="pg-img-cascada@example.com"
    )
    servicio = await create_service(client, token)
    res = await client.post(
        f"/services/{servicio}/image",
        headers=auth_headers(token),
        files={"file": ("foto.jpg", _FOTO, "image/jpeg")},
    )
    assert res.status_code == 200, res.text
    service_id, _ = await _ids(owner_engine, servicio)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("delete from services where id = :i"), {"i": service_id}
        )
        quedan = (
            await conn.execute(text("select count(*) from store_media"))
        ).scalar_one()
    assert quedan == 0


@pytest.mark.asyncio
async def test_el_bytea_de_las_imagenes_no_se_comprime(
    owner_engine: AsyncEngine,
) -> None:
    # F1-30 (R10-07): PNG/JPEG/WebP ya vienen comprimidos; con EXTENDED, TOAST
    # gastaba CPU en pglz sin ahorro. 'e' = EXTERNAL (fuera de linea, sin
    # comprimir).
    async with owner_engine.connect() as conn:
        storage = (
            await conn.execute(
                text(
                    "select attstorage::text from pg_attribute "
                    "where attrelid = 'store_media'::regclass and attname = 'data'"
                )
            )
        ).scalar_one()
    assert storage == "e"


@pytest.mark.asyncio
async def test_desvincular_el_logo_borra_la_fila_bajo_rls(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    # F1-30 (decision 21): el DELETE corre como shifty_app con el contexto de
    # la tienda; RLS lo deja borrar solo lo propio.
    _, token = await register_and_login(
        client, app_sessions, slug="pg-img-logo", email="pg-img-logo@example.com"
    )
    subida = await client.post(
        "/stores/me/media",
        headers=auth_headers(token),
        data={"kind": "logo"},
        files={"file": ("logo.png", png(64, 64), "image/png")},
    )
    assert subida.status_code == 200, subida.text
    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"logo_url": None}
    )
    assert res.status_code == 200, res.text
    async with owner_engine.connect() as conn:
        quedan = (
            await conn.execute(text("select count(*) from store_media"))
        ).scalar_one()
    assert quedan == 0
