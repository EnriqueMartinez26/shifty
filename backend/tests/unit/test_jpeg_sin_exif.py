"""Las fotos JPEG se guardan sin Exif ni XMP (PV-15 de la auditoria de privacidad).

2026-09-24. Una foto sacada con el celular trae en APP1 el Exif (GPS, modelo,
fecha y hora) y el XMP, y en APP2 datos de FlashPix o MPF: el logo o la foto
del servicio los publicaba tal cual en el portal. Sin Pillow (regla 19) no se
re-codifica: se quitan esos segmentos por su longitud, antes del SOF, sin
tocar un byte de la imagen. El perfil de color (APP2 ``ICC_PROFILE``) se
queda: no identifica a nadie y sin el una foto Display P3 se ve lavada.
PNG y WebP se guardan como llegan.
"""

import pytest

from modules.stores.media import (
    image_dimensions,
    jpeg_orientation,
    prepare_image,
    strip_jpeg_app1,
)
from tests.unit.imagenes_sinteticas import (
    APP0_JFIF,
    EXIF,
    ICC,
    IPTC,
    MPF,
    XMP,
    exif_con_orientacion,
    jpeg,
    png,
    webp_vp8l,
)


def test_quita_exif_xmp_mpf_e_iptc_y_deja_el_perfil_de_color() -> None:
    original = jpeg(1061, 1460, EXIF, XMP, ICC, MPF, IPTC)
    limpia = strip_jpeg_app1(original)
    for dato in (b"Exif", b"GPS-privado", b"xap/1.0", b"MPF\x00", b"Photoshop"):
        assert dato in original
        assert dato not in limpia
    assert ICC in limpia
    assert APP0_JFIF in limpia
    # Lo unico que cambia es que faltan esos segmentos: la imagen es la misma.
    assert limpia == jpeg(1061, 1460, ICC)
    assert image_dimensions(limpia, "image/jpeg") == (1061, 1460)


def test_una_foto_sin_metadatos_queda_identica() -> None:
    original = jpeg(800, 600, ICC)
    assert strip_jpeg_app1(original) == original


@pytest.mark.parametrize("intercalado", [b"\xff\xd0", b"\xff\xff", b"\x00" * 16])
def test_respeta_marcadores_sin_longitud_y_basura(intercalado: bytes) -> None:
    original = jpeg(640, 480, EXIF, intercalado, XMP)
    assert strip_jpeg_app1(original) == jpeg(640, 480, intercalado)


def test_un_app1_pegado_despues_del_eoi_no_se_toca() -> None:
    # jpeg() termina en EOI (FF D9): el APP1 va DESPUES del final de la
    # imagen. El recorte se detiene en el SOF, asi que lo que sigue (datos de
    # entropia, EOI y cualquier cola) va tal cual. Recortar la cola despues
    # del EOI (MPF, motion photos) es otro trabajo, no este.
    original = jpeg(100, 100) + EXIF
    assert strip_jpeg_app1(original) == original


def test_prepare_image_limpia_solo_jpeg() -> None:
    data, content_type = prepare_image(jpeg(1061, 1460, EXIF), "service")
    assert content_type == "image/jpeg"
    assert b"Exif" not in data
    for otra in (png(100, 100), webp_vp8l(100, 100)):
        assert prepare_image(otra, "logo")[0] == otra


@pytest.mark.parametrize("orden", ["MM", "II"])
def test_conserva_solo_la_orientacion(orden: str) -> None:
    # Revision de PV-15: sin el tag Orientation (0x0112) una foto vertical
    # del celular se ve acostada. Se reescribe un APP1 minimo con ese unico
    # tag; el GPS y el resto del Exif se van.
    original = jpeg(1061, 1460, exif_con_orientacion(6, orden), XMP)
    assert jpeg_orientation(original) == 6
    limpia = strip_jpeg_app1(original)
    assert b"GPS-privado" not in limpia
    assert b"\x88\x25" not in limpia and b"\x25\x88" not in limpia
    assert b"xap/1.0" not in limpia
    assert jpeg_orientation(limpia) == 6
    assert image_dimensions(limpia, "image/jpeg") == (1061, 1460)
    # El APP1 nuevo va donde estaba el original: antes del SOF.
    assert limpia.index(b"Exif\x00\x00") < limpia.index(b"\xff\xc0")


def test_sin_orientacion_legible_no_se_escribe_nada() -> None:
    # EXIF (el de los otros tests) no trae un TIFF valido: se va entero.
    limpia = strip_jpeg_app1(jpeg(100, 100, EXIF))
    assert b"Exif" not in limpia
    assert jpeg_orientation(limpia) is None
