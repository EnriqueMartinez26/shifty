"""Servido de imagenes con cache HTTP de verdad (F1-27, R10-02 del plan).

2026-09-24: ``GET /stores/media/{id}`` respondia ``max-age=86400`` sin ETag
ni Last-Modified, y el middleware le agregaba ``pragma: no-cache``. Cada
visita al portal revalidaba el logo contra el backend, que leia el bytea
entero (hasta 2 MB) con ~5 idas a la base. HEAD daba 405.

La URL es inmutable: cada upload crea un id nuevo, asi que la respuesta se
cachea un ano (``immutable``) y un ``If-None-Match`` con el id responde 304
SIN abrir la base. Una imagen reemplazada sigue cacheada bajo su id viejo,
que la tienda ya no referencia.
"""

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from main import app
from modules.stores.router import media_router
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.unit.imagenes_sinteticas import jpeg

INMUTABLE = "public, max-age=31536000, immutable"
_FOTO = jpeg(1061, 1460)


async def _logo(client: AsyncClient, slug: str) -> str:
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@example.com")
    res = await client.post(
        "/stores/me/media",
        headers=auth_headers(token),
        data={"kind": "logo"},
        files={"file": ("logo.jpg", _FOTO, "image/jpeg")},
    )
    assert res.status_code == 200, res.text
    return str(res.json()["media_id"])


class _BaseProhibida:
    """Reemplaza ``get_db``: si la ruta abre una sesion, el test falla."""

    def __init__(self) -> None:
        self.aperturas = 0

    async def __call__(self) -> AsyncIterator[AsyncSession]:
        self.aperturas += 1
        raise AssertionError("el 304 no tiene que abrir la base")
        yield  # pragma: no cover - generador


@pytest.fixture
def base_prohibida() -> Iterator[_BaseProhibida]:
    anterior = app.dependency_overrides.get(get_db)
    prohibida = _BaseProhibida()
    app.dependency_overrides[get_db] = prohibida
    try:
        yield prohibida
    finally:
        if anterior is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = anterior


@pytest.mark.asyncio
async def test_la_imagen_se_sirve_inmutable_con_validadores(
    client: AsyncClient,
) -> None:
    media_id = await _logo(client, "cache-media-200")
    res = await client.get(f"/stores/media/{media_id}")
    assert res.status_code == 200
    assert res.content == _FOTO
    assert res.headers["content-type"] == "image/jpeg"
    assert res.headers["cache-control"] == INMUTABLE
    assert res.headers["etag"] == f'"{media_id}"'
    assert res.headers["last-modified"].endswith(" GMT")
    # Sin pragma: con `pragma: no-cache` un cache HTTP/1.0 (y algunos
    # proxies) revalidaban cada vez aunque la ruta dijera un ano.
    assert "pragma" not in res.headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plantilla",
    ['"{id}"', 'W/"{id}"', '"otro", "{id}"'],
    ids=["fuerte", "debil", "lista"],
)
async def test_if_none_match_con_el_id_es_304_sin_abrir_la_base(
    client: AsyncClient, base_prohibida: _BaseProhibida, plantilla: str
) -> None:
    # El id no necesita existir para el 304: la URL es inmutable y el
    # validador ES el id, asi que el backend no consulta nada.
    media_id = "01JZZZZZZZZZZZZZZZZZZZZZZZ"
    res = await client.get(
        f"/stores/media/{media_id}",
        headers={"If-None-Match": plantilla.format(id=media_id)},
    )
    assert res.status_code == 304, res.text
    assert res.content == b""
    assert res.headers["etag"] == f'"{media_id}"'
    assert res.headers["cache-control"] == INMUTABLE
    assert base_prohibida.aperturas == 0


@pytest.mark.asyncio
async def test_if_none_match_de_otro_id_devuelve_la_imagen(
    client: AsyncClient,
) -> None:
    media_id = await _logo(client, "cache-media-otro")
    res = await client.get(
        f"/stores/media/{media_id}", headers={"If-None-Match": '"01OTRO", *'}
    )
    assert res.status_code == 200
    assert res.content == _FOTO


@pytest.mark.asyncio
async def test_head_responde_los_headers_sin_cuerpo(client: AsyncClient) -> None:
    media_id = await _logo(client, "cache-media-head")
    res = await client.head(f"/stores/media/{media_id}")
    assert res.status_code == 200
    assert res.content == b""
    assert res.headers["content-length"] == str(len(_FOTO))
    assert res.headers["content-type"] == "image/jpeg"
    assert res.headers["cache-control"] == INMUTABLE
    assert res.headers["etag"] == f'"{media_id}"'


@pytest.mark.asyncio
async def test_head_de_una_imagen_que_no_existe_es_404(client: AsyncClient) -> None:
    res = await client.head("/stores/media/01JZZZZZZZZZZZZZZZZZZZZZZZ")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_el_resto_de_la_api_sigue_sin_cache_y_con_pragma(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="cache-media-api", email="cache-media-api@example.com"
    )
    res = await client.get("/stores/me", headers=auth_headers(token))
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["pragma"] == "no-cache"


def test_el_router_de_medios_sin_guarda_solo_tiene_lecturas() -> None:
    # Va sin block_writes_when_suspended (main.py): una escritura agregada
    # aca naceria sin la guarda de tienda suspendida.
    metodos = {
        metodo
        for ruta in media_router.routes
        if isinstance(ruta, APIRoute)
        for metodo in ruta.methods
    }
    assert metodos == {"GET", "HEAD"}
