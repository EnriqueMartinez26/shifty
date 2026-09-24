"""Validacion y topes de las imagenes subidas por la tienda (regla 19).

La validacion es por MAGIC BYTES, no por el Content-Type que declara el cliente
(que es falsificable). SVG queda EXCLUIDO a proposito: puede embeber JavaScript y
convertirse en XSS almacenado cuando se sirve inline.

Topes por tipo y FAIL-CLOSED (F1-26, decision 13 del plan de rendimiento,
2026-09-24). El tope unico de 25 MP era "best effort": si no se podian leer
las dimensiones, la imagen pasaba, y un WebP lossless (``VP8L``) nunca se
leia. 16384 x 16384 (268 MP, ~1 GB al decodificar en el navegador de quien
visita el portal) entraba en 2 MB. Ahora una imagen cuyas dimensiones no se
pueden leer se rechaza. Sin Pillow: se leen solo los headers (dependencia
nativa, regla 19); redimensionar es otra decision.
"""

import re
import struct
from dataclasses import dataclass
from typing import Callable

from core.config import settings
from core.exceptions import AppException, ValidationException
from core.validation import reject_unsafe_url


@dataclass(frozen=True)
class ImageCaps:
    """Tope de un tipo de imagen. El lado largo y el corto se miden sin
    importar la orientacion: una portada vertical de 2160 x 3840 entra."""

    max_bytes: int
    max_long_side: int
    max_short_side: int

    @property
    def max_pixels(self) -> int:
        # 4 MP / 8 MP / 2,6 MP del plan son estos productos: un tope de
        # pixeles menor haria inalcanzable la dimension que el plan permite.
        return self.max_long_side * self.max_short_side


_MB = 1024 * 1024

# Se muestran a 40-200 px (logo), <= 1920 px de ancho (portada) y 48-400 px
# (servicio): los topes dejan margen para pantallas de alta densidad.
IMAGE_CAPS: dict[str, ImageCaps] = {
    "logo": ImageCaps(max_bytes=1 * _MB, max_long_side=2048, max_short_side=2048),
    "cover": ImageCaps(max_bytes=2 * _MB, max_long_side=3840, max_short_side=2160),
    "service": ImageCaps(max_bytes=1 * _MB, max_long_side=1600, max_short_side=1600),
}
# Tipos que se suben desde /stores/me/media; la imagen de servicio tiene su
# propio endpoint (POST /services/{id}/image).
ALLOWED_KINDS = ("logo", "cover")

_SNIFFERS: dict[str, Callable[[bytes], bool]] = {
    "image/png": lambda d: d[:8] == b"\x89PNG\r\n\x1a\n",
    "image/jpeg": lambda d: d[:3] == b"\xff\xd8\xff",
    "image/webp": lambda d: len(d) >= 12 and d[:4] == b"RIFF" and d[8:12] == b"WEBP",
}


def detect_image_type(data: bytes) -> str | None:
    """Content-type validado por magic bytes, o None si no es un formato
    permitido (PNG/JPEG/WebP)."""
    for content_type, sniff in _SNIFFERS.items():
        if sniff(data):
            return content_type
    return None


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    # El primer chunk tiene que ser IHDR, pegado a la firma: tipo en el
    # offset 12, ancho y alto uint32 big-endian en 16 y 20.
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return (width, height)


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    # RIFF(4) + tamano(4) + WEBP(4) + fourcc del primer chunk(4) + tamano(4):
    # los datos del chunk empiezan en el offset 20.
    fourcc = data[12:16]
    if fourcc == b"VP8X" and len(data) >= 30:
        # Lienzo extendido: ancho-1 y alto-1 en 24 bits little-endian.
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return (width, height)
    if fourcc == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        # Lossy: frame tag de 3 bytes, codigo de inicio y 14 bits por lado.
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return (width, height)
    if fourcc == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        # Lossless: firma 0x2F y despues ancho-1 y alto-1 en 14 bits cada uno.
        bits = int.from_bytes(data[21:25], "little")
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    # Otro chunk (o uno cortado): no se sabe cuanto mide. Fail-closed.
    return None


# SOF0..SOF15 salvo DHT (C4), JPG (C8) y DAC (CC), que comparten el rango.
_JPEG_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
# Marcadores sin longitud: TEM, RST0..RST7 y SOI.
_JPEG_STANDALONE = frozenset({0x01, *range(0xD0, 0xD9)})
_JPEG_SOS = 0xDA
_JPEG_EOI = 0xD9


# Un JPEG real tiene menos de 30 segmentos antes del SOF (APPn, DQT, DHT,
# DRI, COM). El tope acota el recorrido en Python: sin el, un archivo de
# 2 MB con un marcador cada 2 bytes costaba ~1 M de vueltas (lo mismo que el
# recorrido byte a byte que reemplaza). Pasarlo es imagen ilegible.
_JPEG_MAX_MARKERS = 256
_JPEG_FILL = re.compile(rb"\xff+")


def _next_jpeg_marker(data: bytes, i: int) -> tuple[int, int] | None:
    """(posicion, marcador) del proximo marcador desde ``i``, o None.

    La basura hasta el proximo 0xFF se saltea con ``bytes.find`` y una
    corrida de relleno (0xFF 0xFF ...) con una regex: las dos a velocidad de
    C, como hace el decodificador. Un byte escapado (0xFF 0x00) solo existe
    dentro de los datos de entropia, despues del SOS: antes del SOF es un
    archivo armado a mano y se trata como ilegible.
    """
    i = data.find(b"\xff", i)
    if i < 0:
        return None
    # data[i] es 0xFF: la corrida tiene al menos un byte.
    fill = _JPEG_FILL.match(data, i)
    pos = (fill.end() if fill else i + 1) - 1
    if pos + 1 >= len(data) or data[pos + 1] == 0x00:
        return None
    return (pos, data[pos + 1])


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Recorre los segmentos hasta el SOF, como el decodificador.

    Cada segmento se saltea por su longitud (un SOF escondido dentro de un
    APPn no cuenta); los marcadores sin longitud (RSTn, TEM, SOI) se saltean
    solos. La basura entre segmentos tambien la saltea el decodificador hasta
    el proximo marcador, asi que los dos ven el mismo SOF. Un SOS o un EOI
    antes del SOF, o un segmento cortado, es una imagen sin dimensiones.
    """
    n = len(data)
    i = 2
    for _ in range(_JPEG_MAX_MARKERS):
        found = _next_jpeg_marker(data, i)
        if found is None:
            return None
        i, marker = found
        if marker in _JPEG_STANDALONE:
            i += 2
            continue
        if marker in (_JPEG_SOS, _JPEG_EOI) or i + 4 > n:
            return None
        seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
        if seg_len < 2:
            return None
        if marker in _JPEG_SOF:
            if seg_len < 7 or i + 9 > n:
                return None
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            return (width, height)
        i += 2 + seg_len
    return None


_DIMENSION_READERS: dict[str, Callable[[bytes], tuple[int, int] | None]] = {
    "image/png": _png_dimensions,
    "image/webp": _webp_dimensions,
    "image/jpeg": _jpeg_dimensions,
}


def image_dimensions(data: bytes, content_type: str) -> tuple[int, int] | None:
    """(ancho, alto) declarados en el header, o None si no se pueden leer."""
    reader = _DIMENSION_READERS.get(content_type)
    return reader(data) if reader else None


def validate_image(data: bytes, kind: str) -> str:
    """Content-type de una imagen que respeta el tope de ``kind``.

    Levanta ``AppException``: 413 por bytes; 422 por formato, por dimensiones
    ilegibles o por dimensiones de mas. Nunca deja pasar una imagen de la que
    no sabe cuanto mide.
    """
    caps = IMAGE_CAPS[kind]
    if not data:
        raise AppException("Archivo vacio", http_status=422, error_code="EMPTY_MEDIA")
    if len(data) > caps.max_bytes:
        raise AppException(
            f"La imagen supera el maximo de {caps.max_bytes // _MB} MB",
            http_status=413,
            error_code="MEDIA_TOO_LARGE",
        )
    content_type = detect_image_type(data)
    if content_type is None:
        raise AppException(
            "Formato no permitido. Solo PNG, JPEG o WebP.",
            http_status=422,
            error_code="UNSUPPORTED_MEDIA_TYPE",
        )
    dims = image_dimensions(data, content_type)
    if dims is None or min(dims) < 1:
        raise AppException(
            "No pudimos leer la imagen. Proba exportarla de nuevo como PNG, "
            "JPEG o WebP.",
            http_status=422,
            error_code="INVALID_IMAGE",
        )
    long_side, short_side = max(dims), min(dims)
    if (
        long_side > caps.max_long_side
        or short_side > caps.max_short_side
        or long_side * short_side > caps.max_pixels
    ):
        raise AppException(
            "La imagen es demasiado grande: hasta "
            f"{caps.max_long_side} x {caps.max_short_side} pixeles.",
            http_status=422,
            error_code="IMAGE_TOO_LARGE_DIMENSIONS",
        )
    return content_type


# APP1 (Exif con GPS, modelo y fecha; XMP), APP2 (FlashPix, MPF) y APP13
# (IPTC de Photoshop: autor, ciudad, leyenda). El APP2 que empieza con
# ICC_PROFILE se queda: es el perfil de color, no identifica a nadie.
_JPEG_PRIVATE_APPS = frozenset({0xE1, 0xE2, 0xED})
_ICC_PROFILE = b"ICC_PROFILE\x00"


def strip_jpeg_app1(data: bytes) -> bytes:
    """El JPEG sin sus metadatos personales (PV-15), sin re-codificar.

    Recorre los segmentos como ``_jpeg_dimensions`` y copia todo salvo los
    APPn privados; se detiene en el SOF (o en lo que no pueda leer) y copia
    el resto tal cual, asi que la imagen no cambia ni un byte. Solo JPEG:
    PNG y WebP se guardan como llegan (sus metadatos van en chunks que hoy
    no se tocan).
    """
    n = len(data)
    partes = [data[:2]]
    i = 2
    for _ in range(_JPEG_MAX_MARKERS):
        found = _next_jpeg_marker(data, i)
        if found is None:
            break
        pos, marker = found
        if marker in _JPEG_STANDALONE:
            partes.append(data[i : pos + 2])
            i = pos + 2
            continue
        if marker in _JPEG_SOF or marker in (_JPEG_SOS, _JPEG_EOI) or pos + 4 > n:
            break
        fin = pos + 2 + int.from_bytes(data[pos + 2 : pos + 4], "big")
        if fin <= pos + 3 or fin > n:
            break
        privado = marker in _JPEG_PRIVATE_APPS and not (
            marker == 0xE2 and data[pos + 4 : fin].startswith(_ICC_PROFILE)
        )
        # Lo que habia antes del marcador (relleno o basura) se conserva.
        partes.append(data[i:pos] if privado else data[i:fin])
        i = fin
    partes.append(data[i:])
    return b"".join(partes)


def prepare_image(data: bytes, kind: str) -> tuple[bytes, str]:
    """(bytes a guardar, content-type) de una imagen subida de tipo ``kind``.

    Valida con el tope del tipo (``validate_image``) y, si es JPEG, le quita
    el Exif y el resto de los metadatos personales antes de guardarla.
    """
    content_type = validate_image(data, kind)
    if content_type == "image/jpeg":
        data = strip_jpeg_app1(data)
    return data, content_type


# URL de una imagen subida. Se GUARDA absoluta y del mismo origen
# ({PUBLIC_API_URL}/stores/media/{id}): la release anterior valida image_url
# con reject_unsafe_url (http/https) en ServiceResponse, asi que una ruta
# relativa le daba 500 en un rollback, y el front valida con z.string().url().
# La forma relativa (/api/stores/media/{id}, la de los logos subidos antes de
# F1-28) se sigue aceptando en la entrada. Es inmutable: cada upload crea un
# id nuevo.
_MEDIA_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_RELATIVE_PREFIX = "/api/stores/media/"


def _absolute_prefix() -> str:
    return settings.PUBLIC_API_URL.rstrip("/") + "/stores/media/"


def media_url(media_id: str) -> str:
    return f"{_absolute_prefix()}{media_id}"


def media_id_from_url(value: str | None) -> str | None:
    """El id de una imagen servida por la app, en cualquiera de sus dos
    formas; None si la URL es otra cosa (externa, vacia)."""
    if not value:
        return None
    value = value.strip()
    for prefix in (_absolute_prefix(), _RELATIVE_PREFIX):
        if value.startswith(prefix):
            media_id = value.removeprefix(prefix)
            return media_id if _MEDIA_ID.fullmatch(media_id) else None
    return None


def is_media_url(value: str | None) -> bool:
    return media_id_from_url(value) is not None


def validate_image_url(value: str | None) -> str | None:
    """URL de imagen de entrada: una imagen servida por la app o http(s).

    Solo el FORMATO: que la imagen servida sea del recurso lo decide
    ``resolve_image_link`` (una URL de medios se sube, no se enlaza a mano).
    """
    if value is not None and value.strip().startswith(_RELATIVE_PREFIX):
        if is_media_url(value):
            return value.strip()
    return reject_unsafe_url(value)


def reject_media_url(value: str | None) -> str | None:
    """Alta de un recurso: todavia no tiene imagen subida que enlazar."""
    if is_media_url(value):
        raise ValueError("para usar una imagen subida, subila despues del alta")
    return reject_unsafe_url(value)


def resolve_image_link(
    field: str, current: str | None, new: str | None
) -> tuple[str | None, str | None]:
    """(valor a guardar, id de la imagen subida que queda sin enlazar).

    Regla unica de logo, portada e imagen de servicio (F1-30, decision 21):
    - Una URL de medios con el MISMO id que la actual es la propia (en
      cualquiera de las dos formas): se conserva lo guardado.
    - Otra URL de medios es 422: la imagen se sube, no se enlaza a mano
      (podria ser de otra tienda).
    - Cualquier otro cambio (null, vacio, URL externa) desvincula la imagen
      subida actual, cuya fila hay que borrar.
    """
    current_id = media_id_from_url(current)
    new_id = media_id_from_url(new)
    if new_id is not None:
        if new_id != current_id:
            raise ValidationException(f"{field}: para cambiar la imagen, subila")
        return current, None
    if current_id is not None and new != current:
        return new, current_id
    return new, None


def absolute_media_url(value: str | None, public_api_url: str) -> str | None:
    """La URL de una imagen servida, absoluta (para quien la ve fuera del
    sitio, como el checkout de Mercado Pago). Lo que se guarda desde F1-28 ya
    es absoluto; un logo viejo relativo se completa. Otra URL vuelve tal cual."""
    if value is None or not value.startswith(_RELATIVE_PREFIX):
        return value
    return public_api_url.rstrip("/") + value.removeprefix("/api")
