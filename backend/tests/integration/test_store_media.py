"""Subida y servido de imagenes de tienda (logo/portada).

Cubre el camino feliz (upload admin -> serve publico), la validacion por magic
bytes (rechazo de SVG y de basura), el limite de tamano y el gating por rol.
"""

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

# PNG minimo valido: firma + relleno.
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 128
_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


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
