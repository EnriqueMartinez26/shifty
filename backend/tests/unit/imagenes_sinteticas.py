"""Imagenes sinteticas armadas por header para los tests de medios (F1-26).

Solo se arma lo que lee el validador (firma, IHDR, SOF, chunk de WebP) mas un
relleno: ningun test decodifica pixeles. Las fotos reales (la de referencia de
1061 x 1460 del plan) no se commitean.
"""

import struct
import zlib


def png(width: int, height: int, relleno: int = 64) -> bytes:
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr))
        + b"IHDR"
        + ihdr
        + crc
        + b"\x00" * relleno
    )


def segmento_jpeg(marcador: int, cuerpo: bytes) -> bytes:
    return bytes([0xFF, marcador]) + struct.pack(">H", len(cuerpo) + 2) + cuerpo


def sof0(width: int, height: int) -> bytes:
    componentes = b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return segmento_jpeg(
        0xC0, b"\x08" + struct.pack(">HH", height, width) + b"\x03" + componentes
    )


APP0_JFIF = segmento_jpeg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
EXIF = segmento_jpeg(0xE1, b"Exif\x00\x00MM\x00\x2a" + b"GPS-privado" * 4)
XMP = segmento_jpeg(0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta/>")
ICC = segmento_jpeg(0xE2, b"ICC_PROFILE\x00\x01\x01" + b"perfil" * 4)
MPF = segmento_jpeg(0xE2, b"MPF\x00" + b"\x00" * 16)
IPTC = segmento_jpeg(0xED, b"Photoshop 3.0\x00" + b"8BIM" + b"\x00" * 12)
DQT = segmento_jpeg(0xDB, b"\x00" + b"\x01" * 64)
# Datos de entropia minimos despues del SOS, con un byte relleno (FF 00) y un
# marcador de reinicio, que no llevan longitud.
SOS_Y_DATOS = segmento_jpeg(0xDA, b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00") + (
    b"\x12\x34\xff\x00\x56\xff\xd0\x78" + b"\x00" * 32 + b"\xff\xd9"
)


def jpeg(width: int, height: int, *antes_del_sof: bytes) -> bytes:
    return (
        b"\xff\xd8"
        + APP0_JFIF
        + b"".join(antes_del_sof)
        + DQT
        + sof0(width, height)
        + SOS_Y_DATOS
    )


def _riff(chunk: bytes, datos: bytes) -> bytes:
    cuerpo = b"WEBP" + chunk + struct.pack("<I", len(datos)) + datos
    return b"RIFF" + struct.pack("<I", len(cuerpo)) + cuerpo


def webp_vp8l(width: int, height: int) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    return _riff(b"VP8L", b"\x2f" + struct.pack("<I", bits) + b"\x00" * 16)


def webp_vp8x(width: int, height: int) -> bytes:
    datos = (
        b"\x10\x00\x00\x00"
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )
    return _riff(b"VP8X", datos + b"\x00" * 16)


def webp_vp8(width: int, height: int) -> bytes:
    datos = b"\x10\x02\x00" + b"\x9d\x01\x2a" + struct.pack("<HH", width, height)
    return _riff(b"VP8 ", datos + b"\x00" * 16)
