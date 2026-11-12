"""Contrato del fragmento social que se incluye en enlaces públicos de tienda."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_suspension_por_endpoint import _suspender


@pytest.mark.asyncio
async def test_metadata_por_slug_escapa_datos_y_resuelve_media_publica(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://shifty.example/")
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.example/api")
    store_public_id, _token = await register_and_login(
        client, slug="metadata-uno", email="metadata-uno@test.com"
    )
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    store.name = 'Taller <script>alert("x")</script> & Co'
    store.theme_config = {
        **(store.theme_config or {}),
        "description": 'Cortes & color <b>para vos</b> "hoy"',
        "cover_url": "/api/stores/media/01ARZ3NDEKTSV4RRFFQ69G5FAV",
    }
    await test_session.commit()

    response = await client.get(
        "/public/share-metadata/Metadata-Uno",
        headers={"host": "attacker.example"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("text/html")
    assert "<script>alert" not in response.text
    assert (
        "<title>Taller &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; "
        "&amp; Co | Shifty</title>" in response.text
    )
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; Co" in response.text
    assert (
        "Cortes &amp; color &lt;b&gt;para vos&lt;/b&gt; &quot;hoy&quot;"
        in response.text
    )
    assert (
        'property="og:url" content="https://shifty.example/b/metadata-uno"'
        in response.text
    )
    assert (
        'property="og:image" content="https://api.example/api/stores/media/01ARZ3NDEKTSV4RRFFQ69G5FAV"'
        in response.text
    )
    assert 'name="twitter:card" content="summary_large_image"' in response.text


@pytest.mark.asyncio
async def test_metadata_de_otra_tienda_es_independiente_y_usa_fallback_seguro(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://shifty.example")
    store_public_id, _token = await register_and_login(
        client, slug="metadata-dos", email="metadata-dos@test.com"
    )
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    store.theme_config = {
        **(store.theme_config or {}),
        "cover_url": "javascript:alert(1)",
    }
    await test_session.commit()

    response = await client.get("/public/share-metadata/metadata-dos")

    assert response.status_code == 200, response.text
    assert "<title>Tienda metadata-dos | Shifty</title>" in response.text
    assert 'property="og:title" content="Tienda metadata-dos | Shifty"' in response.text
    assert (
        'property="og:description" content="Reservá turnos online en Tienda metadata-dos."'
        in response.text
    )
    assert (
        'property="og:url" content="https://shifty.example/b/metadata-dos"'
        in response.text
    )
    assert (
        'property="og:image" content="https://shifty-ar.tech/og-shifty.jpg"'
        in response.text
    )
    schema = (await client.get("/openapi.json")).json()
    assert "/public/share-metadata/{slug}" not in schema["paths"]


@pytest.mark.asyncio
async def test_metadata_sin_portada_usa_la_imagen_general_y_conserva_el_nombre(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://shifty.example")
    store_public_id, _token = await register_and_login(
        client, slug="metadata-sin-portada", email="metadata-sin-portada@test.com"
    )
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    store.theme_config = {
        **(store.theme_config or {}),
        "description": None,
        "cover_url": None,
    }
    await test_session.commit()

    response = await client.get("/public/share-metadata/metadata-sin-portada")

    assert response.status_code == 200, response.text
    assert "<title>Tienda metadata-sin-portada | Shifty</title>" in response.text
    assert (
        'property="og:title" content="Tienda metadata-sin-portada | Shifty"'
        in response.text
    )
    assert (
        'property="og:description" content="Reservá turnos online en '
        'Tienda metadata-sin-portada."' in response.text
    )
    assert (
        'property="og:image" content="https://shifty-ar.tech/og-shifty.jpg"'
        in response.text
    )


@pytest.mark.asyncio
async def test_metadata_de_tienda_inexistente_o_no_visible_devuelve_404_neutro(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store_public_id, _token = await register_and_login(
        client, slug="metadata-oculta", email="metadata-oculta@test.com"
    )
    await test_session.execute(
        update(Store).where(Store.public_id == store_public_id).values(is_active=False)
    )
    await test_session.commit()

    oculta = await client.get("/public/share-metadata/metadata-oculta")
    inexistente = await client.get("/public/share-metadata/no-existe")
    ficha_inexistente = await client.get("/public/stores/no-existe")

    assert (
        oculta.status_code
        == inexistente.status_code
        == ficha_inexistente.status_code
        == 404
    )
    assert oculta.json()["error_code"] == inexistente.json()["error_code"]
    assert inexistente.json()["error_code"] == ficha_inexistente.json()["error_code"]


@pytest.mark.asyncio
async def test_metadata_de_tienda_suspendida_devuelve_404_neutro_y_no_store(
    client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    store_public_id, _token = await register_and_login(
        client, slug="metadata-suspendida", email="metadata-suspendida@test.com"
    )
    await _suspender(test_session, store_public_id)

    metadata = await client.get("/public/share-metadata/metadata-suspendida")
    ficha = await client.get("/public/stores/metadata-suspendida")

    assert metadata.status_code == ficha.status_code == 404
    assert metadata.json()["error_code"] == ficha.json()["error_code"]
    assert metadata.headers.get("cache-control") == "no-store"
