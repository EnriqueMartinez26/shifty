"""Topes de imagen por tipo y fail-closed (F1-26, decision 13 del plan).

2026-09-24, R10-05 / R8-10: el tope era de 25 MP para todo tipo y "best
effort": si no se podian leer las dimensiones, la imagen pasaba. Un WebP
lossless (``VP8L``) no se parseaba, asi que 16384 x 16384 (268 MP, ~1 GB al
decodificar en el navegador del visitante) entraba en 2 MB. Un JPEG con un
marcador sin longitud (RSTn, TEM) antes del SOF desalineaba el recorrido.
Ahora cada tipo tiene su tope (logo, portada, imagen de servicio) y una
imagen cuyas dimensiones no se pueden leer se rechaza.
"""

import pytest

from core.exceptions import AppException
from modules.stores.media import IMAGE_CAPS, image_dimensions, validate_image
from tests.unit.imagenes_sinteticas import (
    EXIF,
    ICC,
    jpeg,
    png,
    segmento_jpeg,
    webp_vp8,
    webp_vp8l,
    webp_vp8x,
)

TIPOS = ("logo", "cover", "service")


def _rechazo(data: bytes, kind: str) -> AppException:
    with pytest.raises(AppException) as exc:
        validate_image(data, kind)
    return exc.value


# -- lectura de dimensiones ----------------------------------------------------


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (png(1061, 1460), "image/png"),
        (jpeg(1061, 1460), "image/jpeg"),
        (jpeg(1061, 1460, EXIF, ICC), "image/jpeg"),
        (webp_vp8l(1061, 1460), "image/webp"),
        (webp_vp8x(1061, 1460), "image/webp"),
        (webp_vp8(1061, 1460), "image/webp"),
    ],
    ids=["png", "jpeg", "jpeg-exif", "webp-vp8l", "webp-vp8x", "webp-vp8"],
)
def test_lee_ancho_y_alto_de_cada_formato(data: bytes, content_type: str) -> None:
    assert image_dimensions(data, content_type) == (1061, 1460)


def test_vp8l_lee_los_14_bits_de_cada_lado() -> None:
    assert image_dimensions(webp_vp8l(16384, 16384), "image/webp") == (16384, 16384)
    assert image_dimensions(webp_vp8l(1, 1), "image/webp") == (1, 1)


@pytest.mark.parametrize(
    "intercalado",
    [
        # Marcadores sin longitud: RST0..RST7, TEM y un SOI repetido.
        b"\xff\xd0",
        b"\xff\xd7",
        b"\xff\x01",
        b"\xff\xd8",
        # Bytes de relleno 0xFF antes de un marcador.
        b"\xff\xff\xff",
        # Basura entre segmentos: el decodificador la saltea hasta el
        # proximo 0xFF, y el validador tiene que ver el mismo SOF.
        b"\x00" * 4096,
    ],
    ids=["rst0", "rst7", "tem", "soi", "relleno", "basura"],
)
def test_jpeg_con_marcadores_sin_longitud_llega_al_sof(intercalado: bytes) -> None:
    # Antes, `FF D0` se leia como un segmento con longitud y el salto caia
    # en cualquier lado: el SOF quedaba sin ver y la imagen pasaba sin tope.
    data = jpeg(1061, 1460, intercalado)
    assert image_dimensions(data, "image/jpeg") == (1061, 1460)


def test_jpeg_exif_con_un_sof_falso_adentro_no_engana() -> None:
    # Un segmento APPn se saltea por su longitud: un SOF de 1x1 escondido en
    # sus datos no es el de la imagen.
    falso = segmento_jpeg(
        0xE1, b"Exif\x00\x00" + b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01"
    )
    assert image_dimensions(jpeg(4000, 4000, falso), "image/jpeg") == (4000, 4000)


# -- fail-closed ---------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128, id="png-sin-ihdr"),
        pytest.param(png(100, 100)[:20], id="png-cortado"),
        pytest.param(b"\xff\xd8\xff\xe0" + b"\x00" * 128, id="jpeg-sin-sof"),
        pytest.param(jpeg(100, 100)[:60], id="jpeg-cortado-antes-del-sof"),
        pytest.param(
            b"\xff\xd8" + segmento_jpeg(0xDA, b"\x00" * 10) + jpeg(100, 100)[2:],
            id="jpeg-sos-antes-del-sof",
        ),
        pytest.param(webp_vp8l(100, 100)[:22], id="vp8l-cortado"),
        pytest.param(
            webp_vp8l(100, 100)[:20] + b"\x00" + webp_vp8l(100, 100)[21:],
            id="vp8l-sin-firma",
        ),
        pytest.param(
            webp_vp8(100, 100).replace(b"\x9d\x01\x2a", b"\x00\x00\x00"),
            id="vp8-sin-codigo-de-inicio",
        ),
        pytest.param(
            webp_vp8l(100, 100).replace(b"VP8L", b"ALPH"), id="webp-chunk-desconocido"
        ),
        pytest.param(png(0, 100), id="png-ancho-cero"),
        pytest.param(jpeg(100, 0), id="jpeg-alto-cero"),
    ],
)
@pytest.mark.parametrize("kind", TIPOS)
def test_si_no_se_leen_las_dimensiones_se_rechaza(data: bytes, kind: str) -> None:
    error = _rechazo(data, kind)
    assert error.http_status == 422
    assert error.error_code == "INVALID_IMAGE"


@pytest.mark.parametrize("kind", TIPOS)
def test_vp8l_de_16384_por_lado_es_422(kind: str) -> None:
    error = _rechazo(webp_vp8l(16384, 16384), kind)
    assert error.http_status == 422
    assert error.error_code == "IMAGE_TOO_LARGE_DIMENSIONS"


@pytest.mark.parametrize("kind", TIPOS)
def test_formato_no_permitido_es_422(kind: str) -> None:
    error = _rechazo(b"<svg xmlns='http://www.w3.org/2000/svg'/>", kind)
    assert (error.http_status, error.error_code) == (422, "UNSUPPORTED_MEDIA_TYPE")


@pytest.mark.parametrize("kind", TIPOS)
def test_archivo_vacio_es_422(kind: str) -> None:
    assert _rechazo(b"", kind).error_code == "EMPTY_MEDIA"


# -- topes por tipo --------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "entra", "no_entra"),
    [
        ("logo", (2048, 2048), (2049, 10)),
        ("logo", (2048, 2048), (10, 2049)),
        ("cover", (3840, 2160), (3841, 100)),
        # La portada admite vertical: el lado largo hasta 3840, el corto hasta 2160.
        ("cover", (2160, 3840), (2161, 2161)),
        ("service", (1600, 1600), (1601, 10)),
        ("service", (1600, 1600), (10, 1601)),
    ],
)
def test_tope_de_dimensiones_por_tipo(
    kind: str, entra: tuple[int, int], no_entra: tuple[int, int]
) -> None:
    assert validate_image(png(*entra), kind) == "image/png"
    error = _rechazo(png(*no_entra), kind)
    assert (error.http_status, error.error_code) == (422, "IMAGE_TOO_LARGE_DIMENSIONS")


@pytest.mark.parametrize(
    ("kind", "maximo"),
    [("logo", 1024 * 1024), ("cover", 2 * 1024 * 1024), ("service", 1024 * 1024)],
)
def test_tope_de_bytes_por_tipo(kind: str, maximo: int) -> None:
    assert IMAGE_CAPS[kind].max_bytes == maximo
    base = png(100, 100)
    justo = base + b"\x00" * (maximo - len(base))
    assert validate_image(justo, kind) == "image/png"
    error = _rechazo(justo + b"\x00", kind)
    assert (error.http_status, error.error_code) == (413, "MEDIA_TOO_LARGE")


@pytest.mark.parametrize("kind", TIPOS)
def test_la_foto_de_referencia_entra_en_los_tres_topes(kind: str) -> None:
    # 1061 x 1460 (1,55 MP), JPEG: la imagen de las pruebas manuales del plan.
    assert validate_image(jpeg(1061, 1460, EXIF), kind) == "image/jpeg"


def test_los_topes_de_pixeles_son_los_del_plan() -> None:
    # 4 MP, 8 MP y 2,6 MP del plan son los productos de las dimensiones
    # maximas (2048^2, 3840x2160 y 1600^2): un tope menor haria inalcanzable
    # la dimension que el mismo plan permite.
    assert IMAGE_CAPS["logo"].max_pixels == 2048 * 2048
    assert IMAGE_CAPS["cover"].max_pixels == 3840 * 2160
    assert IMAGE_CAPS["service"].max_pixels == 1600 * 1600
