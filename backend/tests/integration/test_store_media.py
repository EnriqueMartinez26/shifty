"""Subida y servido de imagenes de tienda (logo/portada).

Cubre el camino feliz (upload admin -> serve publico), la validacion por magic
bytes (rechazo de SVG y de basura), el limite de tamano y el gating por rol.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.stores.model import Store, StoreMedia
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.unit.imagenes_sinteticas import jpeg, png, webp_vp8l

# PNG con IHDR legible: desde F1-26 una imagen sin dimensiones se rechaza.
_PNG = png(64, 64)
_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


async def _subir(
    client: AsyncClient, token: str, kind: str, data: bytes, nombre: str = "img"
) -> tuple[int, dict[str, object]]:
    res = await client.post(
        "/stores/me/media",
        headers=auth_headers(token),
        data={"kind": kind},
        files={"file": (nombre, data, "application/octet-stream")},
    )
    return res.status_code, res.json()


@pytest.mark.asyncio
async def test_upload_logo_and_serve_publicly(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="media-alfa", email="media-alfa@example.com"
    )

    res = await client.post(
        "/stores/me/media",
        headers=auth_headers(token),
        data={"kind": "logo"},
        files={"file": ("logo.png", _PNG, "image/png")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["kind"] == "logo"
    url = body["url"]
    assert url.startswith("/api/stores/media/")

    # El store ahora referencia esa URL como logo.
    me = await client.get("/stores/me", headers=auth_headers(token))
    assert me.json()["logo_url"] == url

    # Servido publico (SIN token) con el content-type correcto y los mismos bytes.
    media_id = url.rsplit("/", 1)[-1]
    served = await client.get(f"/stores/media/{media_id}")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/png")
    assert served.content == _PNG


@pytest.mark.asyncio
async def test_upload_rejects_svg_and_garbage(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="media-beta", email="media-beta@example.com"
    )

    svg = await client.post(
        "/stores/me/media",
        headers=auth_headers(token),
        data={"kind": "logo"},
        files={"file": ("evil.svg", _SVG, "image/svg+xml")},
    )
    assert svg.status_code == 422, svg.text
    assert svg.json()["error_code"] == "UNSUPPORTED_MEDIA_TYPE"

    garbage = await client.post(
        "/stores/me/media",
        headers=auth_headers(token),
        data={"kind": "logo"},
        files={"file": ("x.png", b"not-an-image", "image/png")},
    )
    assert garbage.status_code == 422


@pytest.mark.asyncio
async def test_upload_rejects_invalid_kind(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="media-gamma", email="media-gamma@example.com"
    )
    res = await client.post(
        "/stores/me/media",
        headers=auth_headers(token),
        data={"kind": "banner"},
        files={"file": ("logo.png", _PNG, "image/png")},
    )
    assert res.status_code == 422
    assert res.json()["error_code"] == "INVALID_MEDIA_KIND"


@pytest.mark.asyncio
async def test_serve_missing_media_is_404(client: AsyncClient) -> None:
    await register_and_login(
        client, slug="media-delta", email="media-delta@example.com"
    )
    res = await client.get("/stores/media/01JZZZZZZZZZZZZZZZZZZZZZZZ")
    assert res.status_code == 404
    assert res.json()["error_code"] == "MEDIA_NOT_FOUND"


# -- F1-26: topes por tipo, fail-closed ------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["logo", "cover"])
async def test_webp_lossless_gigante_es_422(client: AsyncClient, kind: str) -> None:
    # 2026-09-24 (R10-05): un VP8L no se parseaba y 16384 x 16384 (268 MP)
    # entraba en 2 MB como si no tuviera dimensiones.
    _, token = await register_and_login(
        client, slug=f"media-vp8l-{kind}", email=f"media-vp8l-{kind}@example.com"
    )
    status, body = await _subir(client, token, kind, webp_vp8l(16384, 16384))
    assert status == 422, body
    assert body["error_code"] == "IMAGE_TOO_LARGE_DIMENSIONS"


@pytest.mark.asyncio
async def test_imagen_sin_dimensiones_legibles_es_422(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="media-sin-ihdr", email="media-sin-ihdr@example.com"
    )
    sin_ihdr = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
    status, body = await _subir(client, token, "logo", sin_ihdr)
    assert status == 422, body
    assert body["error_code"] == "INVALID_IMAGE"


@pytest.mark.asyncio
async def test_el_logo_tiene_tope_de_1_mb_y_la_portada_de_2(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="media-bytes", email="media-bytes@example.com"
    )
    base = png(100, 100)
    un_mb_y_algo = base + b"\x00" * (1024 * 1024 + 1 - len(base))
    status, body = await _subir(client, token, "logo", un_mb_y_algo)
    assert status == 413, body
    assert body["error_code"] == "MEDIA_TOO_LARGE"
    status, body = await _subir(client, token, "cover", un_mb_y_algo)
    assert status == 200, body


@pytest.mark.asyncio
async def test_el_logo_tiene_tope_de_2048_por_lado(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="media-lado", email="media-lado@example.com"
    )
    status, body = await _subir(client, token, "logo", png(2049, 100))
    assert status == 422, body
    assert body["error_code"] == "IMAGE_TOO_LARGE_DIMENSIONS"
    status, body = await _subir(client, token, "cover", png(2049, 100))
    assert status == 200, body


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["logo", "cover"])
async def test_la_foto_de_referencia_entra_como_logo_y_portada(
    client: AsyncClient, kind: str
) -> None:
    _, token = await register_and_login(
        client, slug=f"media-ref-{kind}", email=f"media-ref-{kind}@example.com"
    )
    status, body = await _subir(client, token, kind, jpeg(1061, 1460), "foto.jpg")
    assert status == 200, body


# -- F1-30: desvincular borra la fila (decision 21) -------------------------------


async def _filas(db: AsyncSession, store_public_id: str) -> list[str]:
    result = await db.execute(
        select(StoreMedia.id)
        .join(Store, Store.id == StoreMedia.store_id)
        .where(Store.public_id == store_public_id)
    )
    return [str(fila) for fila in result.scalars()]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "campo", "nuevo"),
    [
        ("logo", "logo_url", None),
        ("logo", "logo_url", ""),
        ("logo", "logo_url", "https://cdn.example.com/logo.png"),
        ("cover", "cover_url", None),
        ("cover", "cover_url", "https://cdn.example.com/portada.jpg"),
    ],
    ids=["logo-null", "logo-vacio", "logo-externo", "portada-null", "portada-externa"],
)
async def test_desvincular_la_imagen_borra_su_fila(
    client: AsyncClient,
    test_session: AsyncSession,
    kind: str,
    campo: str,
    nuevo: str | None,
) -> None:
    # 2026-09-24 (R10-07): la fila quedaba huerfana en store_media al
    # cambiar el logo por una URL o vaciarlo; solo otra subida la borraba.
    slug = f"media-unlink-{kind}-{'null' if nuevo is None else len(nuevo)}"
    store_public_id, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    status, subida = await _subir(client, token, kind, _PNG)
    assert status == 200, subida
    media_id = str(subida["media_id"])

    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json={campo: nuevo}
    )
    assert res.status_code == 200, res.text
    assert res.json()[campo] == (nuevo or None)
    assert (await client.get(f"/stores/media/{media_id}")).status_code == 404
    assert await _filas(test_session, store_public_id) == []


@pytest.mark.asyncio
async def test_devolver_la_misma_url_o_tocar_otro_campo_no_borra(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="media-keep", email="media-keep@example.com"
    )
    _, logo = await _subir(client, token, "logo", _PNG)
    _, portada = await _subir(client, token, "cover", _PNG)

    for cuerpo in (
        {"name": "Otro nombre"},
        {"logo_url": logo["url"], "cover_url": portada["url"]},
    ):
        res = await client.patch("/stores/me", headers=auth_headers(token), json=cuerpo)
        assert res.status_code == 200, res.text
    assert sorted(await _filas(test_session, store_public_id)) == sorted(
        [str(logo["media_id"]), str(portada["media_id"])]
    )


@pytest.mark.asyncio
async def test_no_se_enlaza_a_mano_una_imagen_servida_ajena(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="media-ajena", email="media-ajena@example.com"
    )
    res = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"logo_url": "/api/stores/media/01JZZZZZZZZZZZZZZZZZZZZZZZ"},
    )
    assert res.status_code == 422, res.text
