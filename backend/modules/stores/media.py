"""Validacion y limites de las imagenes subidas por la tienda (logo/portada).

La validacion es por MAGIC BYTES, no por el Content-Type que declara el cliente
(que es falsificable). SVG queda EXCLUIDO a proposito: puede embeber JavaScript y
convertirse en XSS almacenado cuando se sirve inline.
"""

import struct
from typing import Callable

MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2 MB
# Tope de pixeles: dentro de 2MB entra un PNG/WebP declarando 30000x30000
# (~3.6GB al decodificar) = bomba de pixeles para el navegador del visitante.
# 25 MP (~5000x5000) es holgado para un logo/portada real.
MAX_IMAGE_PIXELS = 25_000_000
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
    # IHDR va inmediatamente despues de la firma de 8 bytes: width/height son
    # uint32 big-endian en los offsets 16 y 20.
    if len(data) >= 24 and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    return None


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30:
        return None
    fourcc = data[12:16]
    if fourcc == b"VP8X" and len(data) >= 30:
        w = int.from_bytes(data[24:27], "little") + 1
        h = int.from_bytes(data[27:30], "little") + 1
        return (w, h)
    if fourcc == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        w = int.from_bytes(data[26:28], "little") & 0x3FFF
        h = int.from_bytes(data[28:30], "little") & 0x3FFF
        return (w, h)
    return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    # Se recorren los marcadores hasta el SOF (Start Of Frame), que trae alto y
    # ancho. Se evitan APPn/DQT/etc. saltando por su longitud.
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            return (width, height)
        seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
        if seg_len <= 0:
            return None
        i += 2 + seg_len
    return None


def exceeds_pixel_budget(data: bytes, content_type: str) -> bool:
    """True si las dimensiones declaradas superan MAX_IMAGE_PIXELS. Best-effort:
    si no se pueden determinar, no bloquea (el tope de 2MB ya acota el resto)."""
    dims: tuple[int, int] | None = None
    if content_type == "image/png":
        dims = _png_dimensions(data)
    elif content_type == "image/webp":
        dims = _webp_dimensions(data)
    elif content_type == "image/jpeg":
        dims = _jpeg_dimensions(data)
    if dims is None:
        return False
    width, height = dims
    return width * height > MAX_IMAGE_PIXELS
