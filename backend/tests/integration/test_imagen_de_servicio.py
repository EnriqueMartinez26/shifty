"""Imagen de servicio subida a ``store_media`` (F1-28, decision 12 del plan).

2026-09-24, R10-01: la CSP del front solo permite imagenes de ``'self'``,
pero ``services.image_url`` exigia una URL http(s) externa: toda imagen de
servicio salia rota en el portal y en el panel. Ahora la imagen se sube como
la del logo (``POST /services/{id}/image``, multipart, mismos controles con
el tope de servicio) y ``image_url`` pasa a ser la URL servida, absoluta y
del mismo origen (``{PUBLIC_API_URL}/stores/media/{id}``): la release
anterior valida ``image_url`` con ``reject_unsafe_url`` en la respuesta y
una ruta relativa le daria 500 en un rollback. La forma relativa
(``/api/stores/media/{id}``) se sigue aceptando en la entrada. Una URL
http(s) externa tambien, por ahora (el front migra aparte).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.validation import reject_unsafe_url
from modules.services.model import Service
from modules.stores.media import absolute_media_url
from modules.stores.model import StoreMedia
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    register_and_login,
)
from tests.unit.imagenes_sinteticas import EXIF, jpeg, png, webp_vp8l

_FOTO = jpeg(1061, 1460)


async def _tienda_con_servicio(client: AsyncClient, slug: str) -> tuple[str, str, str]:
    store_public_id, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    return store_public_id, token, await create_service(client, token)


async def _subir(
    client: AsyncClient, token: str, servicio: str, data: bytes = _FOTO
) -> tuple[int, dict[str, object]]:
    res = await client.post(
        f"/services/{servicio}/image",
        headers=auth_headers(token),
        files={"file": ("foto.jpg", data, "image/jpeg")},
    )
    return res.status_code, res.json()


def _media_id(url: object) -> str:
    base = f"{settings.PUBLIC_API_URL}/stores/media/"
    assert isinstance(url, str) and url.startswith(base), url
    return url.removeprefix(base)


async def _filas_del_servicio(db: AsyncSession, servicio: str) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(StoreMedia)
            .join(Service, Service.id == StoreMedia.service_id)
            .where(Service.public_id == servicio)
        )
        or 0
    )


@pytest.mark.asyncio
async def test_subir_la_imagen_la_sirve_y_la_publica_en_el_catalogo(
    client: AsyncClient,
) -> None:
    store_public_id, token, servicio = await _tienda_con_servicio(
        client, "img-svc-alfa"
    )

    status, body = await _subir(client, token, servicio)
    assert status == 200, body
    url = body["image_url"]
    media_id = _media_id(url)

    servida = await client.get(f"/stores/media/{media_id}")
    assert servida.status_code == 200
    assert servida.content == _FOTO
    assert servida.headers["content-type"] == "image/jpeg"

    catalogo = await client.get(
        "/public/services", params={"store_public_id": store_public_id}
    )
    assert catalogo.status_code == 200
    (publicado,) = catalogo.json()
    assert publicado["image_url"] == url

    panel = await client.get(f"/services/{servicio}", headers=auth_headers(token))
    assert panel.json()["image_url"] == url


@pytest.mark.asyncio
async def test_reemplazar_la_imagen_borra_la_anterior(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token, servicio = await _tienda_con_servicio(client, "img-svc-beta")
    _, primera = await _subir(client, token, servicio)
    _, segunda = await _subir(client, token, servicio, png(800, 600))
    vieja = _media_id(primera["image_url"])
    nueva = _media_id(segunda["image_url"])
    assert vieja != nueva

    assert (await client.get(f"/stores/media/{vieja}")).status_code == 404
    assert (await client.get(f"/stores/media/{nueva}")).status_code == 200
    assert await _filas_del_servicio(test_session, servicio) == 1


@pytest.mark.asyncio
async def test_borrar_la_imagen_la_desvincula_y_borra_la_fila(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token, servicio = await _tienda_con_servicio(client, "img-svc-gamma")
    _, subida = await _subir(client, token, servicio)
    media_id = _media_id(subida["image_url"])

    res = await client.delete(
        f"/services/{servicio}/image", headers=auth_headers(token)
    )
    assert res.status_code == 200, res.text
    assert res.json()["image_url"] is None
    assert (await client.get(f"/stores/media/{media_id}")).status_code == 404
    assert await _filas_del_servicio(test_session, servicio) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "status", "error_code"),
    [
        (png(1601, 100), 422, "IMAGE_TOO_LARGE_DIMENSIONS"),
        (webp_vp8l(16384, 16384), 422, "IMAGE_TOO_LARGE_DIMENSIONS"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, 422, "INVALID_IMAGE"),
        (png(100, 100) + b"\x00" * (1024 * 1024), 413, "MEDIA_TOO_LARGE"),
        (b"<svg/>", 422, "UNSUPPORTED_MEDIA_TYPE"),
    ],
    ids=["1601px", "vp8l-gigante", "sin-ihdr", "mas-de-1mb", "svg"],
)
async def test_la_imagen_de_servicio_respeta_su_tope(
    client: AsyncClient, data: bytes, status: int, error_code: str
) -> None:
    _, token, servicio = await _tienda_con_servicio(
        client, f"img-svc-tope-{status}-{len(data)}"
    )
    got, body = await _subir(client, token, servicio, data)
    assert got == status, body
    assert body["error_code"] == error_code


@pytest.mark.asyncio
async def test_el_servicio_de_otra_tienda_es_404(client: AsyncClient) -> None:
    _, _, ajeno = await _tienda_con_servicio(client, "img-svc-ajena")
    _, token_propio, _ = await _tienda_con_servicio(client, "img-svc-propia")
    status, body = await _subir(client, token_propio, ajeno)
    assert status == 404, body


@pytest.mark.asyncio
async def test_el_patch_acepta_la_url_propia_y_rechaza_otra_de_medios(
    client: AsyncClient,
) -> None:
    # El front manda el formulario entero: devolver la URL que ya tiene no
    # puede ser 422. Apuntar a otra imagen servida si: se sube, no se enlaza.
    _, token, servicio = await _tienda_con_servicio(client, "img-svc-patch")
    _, subida = await _subir(client, token, servicio)
    propia = subida["image_url"]

    igual = await client.patch(
        f"/services/{servicio}",
        headers=auth_headers(token),
        json={"image_url": propia, "name": "Consulta larga"},
    )
    assert igual.status_code == 200, igual.text

    # La forma relativa del mismo id tambien es la propia, y no cambia lo
    # guardado.
    relativa = await client.patch(
        f"/services/{servicio}",
        headers=auth_headers(token),
        json={"image_url": f"/api/stores/media/{_media_id(propia)}"},
    )
    assert relativa.status_code == 200, relativa.text
    assert relativa.json()["image_url"] == propia

    for ajena_url in (
        "/api/stores/media/01JZZZZZZZZZZZZZZZZZZZZZZZ",
        f"{settings.PUBLIC_API_URL}/stores/media/01JZZZZZZZZZZZZZZZZZZZZZZZ",
    ):
        ajena = await client.patch(
            f"/services/{servicio}",
            headers=auth_headers(token),
            json={"image_url": ajena_url},
        )
        assert ajena.status_code == 422, ajena.text


@pytest.mark.asyncio
@pytest.mark.parametrize("forma", ["relativa", "absoluta"])
async def test_crear_con_una_url_de_medios_es_422(
    client: AsyncClient, forma: str
) -> None:
    _, token = await register_and_login(
        client, slug=f"img-svc-alta-{forma}", email=f"img-svc-alta-{forma}@example.com"
    )
    base = "/api" if forma == "relativa" else settings.PUBLIC_API_URL
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={
            "name": "Consulta",
            "duration_minutes": 30,
            "price": 1000,
            "image_url": f"{base}/stores/media/01JZZZZZZZZZZZZZZZZZZZZZZZ",
        },
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_la_url_guardada_la_acepta_la_release_anterior(
    client: AsyncClient,
) -> None:
    # Rollback (expand/contract): la release anterior valida image_url con
    # reject_unsafe_url en ServiceResponse; una ruta relativa le daba 500.
    _, token, servicio = await _tienda_con_servicio(client, "img-svc-rollback")
    _, subida = await _subir(client, token, servicio)
    url = str(subida["image_url"])
    assert reject_unsafe_url(url) == url


@pytest.mark.asyncio
async def test_una_url_externa_se_sigue_aceptando(client: AsyncClient) -> None:
    _, token, servicio = await _tienda_con_servicio(client, "img-svc-externa")
    res = await client.patch(
        f"/services/{servicio}",
        headers=auth_headers(token),
        json={"image_url": "https://cdn.example.com/corte.jpg"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["image_url"] == "https://cdn.example.com/corte.jpg"


def test_la_url_de_medios_se_vuelve_absoluta_para_mercado_pago() -> None:
    # MP muestra `picture_url` en su checkout, fuera del sitio: una ruta
    # relativa no le sirve.
    # Lo que se guarda desde F1-28 ya es absoluto; un logo viejo (relativo)
    # se completa con la base publica.
    base = "https://shifty.example.com/api/"
    assert (
        absolute_media_url("/api/stores/media/01ABC", base)
        == "https://shifty.example.com/api/stores/media/01ABC"
    )
    absoluta = f"{settings.PUBLIC_API_URL}/stores/media/01ABC"
    assert absolute_media_url(absoluta, base) == absoluta
    assert absolute_media_url("https://cdn.example.com/x.jpg", base) == (
        "https://cdn.example.com/x.jpg"
    )
    assert absolute_media_url(None, base) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("nuevo", [None, "https://cdn.example.com/corte.jpg"])
async def test_el_patch_que_desvincula_la_imagen_borra_la_fila(
    client: AsyncClient, test_session: AsyncSession, nuevo: str | None
) -> None:
    # F1-30 (decision 21): la imagen subida que deja de estar enlazada no
    # queda huerfana en store_media.
    slug = f"img-svc-unlink-{'null' if nuevo is None else 'url'}"
    _, token, servicio = await _tienda_con_servicio(client, slug)
    _, subida = await _subir(client, token, servicio)
    media_id = _media_id(subida["image_url"])

    res = await client.patch(
        f"/services/{servicio}", headers=auth_headers(token), json={"image_url": nuevo}
    )
    assert res.status_code == 200, res.text
    assert res.json()["image_url"] == nuevo
    assert (await client.get(f"/stores/media/{media_id}")).status_code == 404
    assert await _filas_del_servicio(test_session, servicio) == 0


@pytest.mark.asyncio
async def test_la_foto_del_servicio_se_publica_sin_exif(client: AsyncClient) -> None:
    _, token, servicio = await _tienda_con_servicio(client, "img-svc-exif")
    status, body = await _subir(client, token, servicio, jpeg(1061, 1460, EXIF))
    assert status == 200, body
    servida = await client.get(f"/stores/media/{_media_id(body['image_url'])}")
    assert b"GPS-privado" not in servida.content
    assert servida.headers["content-length"] == str(len(jpeg(1061, 1460)))
