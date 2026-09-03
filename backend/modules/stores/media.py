"""Validacion y limites de las imagenes subidas por la tienda (logo/portada).

La validacion es por MAGIC BYTES, no por el Content-Type que declara el cliente
(que es falsificable). SVG queda EXCLUIDO a proposito: puede embeber JavaScript y
convertirse en XSS almacenado cuando se sirve inline.
"""

from typing import Callable

MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2 MB
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
