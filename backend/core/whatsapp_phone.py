"""Telefonos para links de wa.me, con la regla del front.

Port de ``frontend/src/shared/utils/whatsAppPhone.ts``
(``normalizePhoneForWhatsApp``): el backend decide si el WhatsApp de la tienda
es un canal para cobrar una sena (decision de Mateo, 2026-10-03) y tiene que
coincidir con el front, que con un numero que no puede leer no muestra el
boton de "Coordinar el pago por WhatsApp". Los casos viven en UN archivo,
``frontend/src/shared/utils/whatsAppPhone.cases.json``, que leen
``tests/unit/test_whatsapp_phone.py`` y ``whatsAppPhone.test.ts``.

wa.me exige el numero internacional, solo digitos y sin "+". Un celular
argentino es 54 + 9 + codigo de area + abonado (10 digitos, sin el 0 de larga
distancia ni el 15 de celular). Cuando el numero no se puede leer con
confianza devuelve ``None``: mejor sin canal que mandar a otra persona.
"""

from __future__ import annotations

import re

_ARGENTINA_CODE = "54"
_ARGENTINA_MOBILE = "549"
_NATIONAL_LENGTH = 10
_NATIONAL_WITH_15_LENGTH = 12
# E.164: hasta 15 digitos con el codigo de pais; menos de 8 no es un telefono.
_MIN_INTERNATIONAL_LENGTH = 8
_MAX_INTERNATIONAL_LENGTH = 15

# Espacios que se leen como separadores: los mismos en los dos lados (los de
# la clase ``\s`` de JavaScript). Revision 4R de la PR #108: el front aceptaba
# un numero con NBSP, espacio fino o BOM (``\s`` y ``trim`` de JS los
# incluyen) y el back, con ``re.ASCII``, no: un WhatsApp pegado desde
# WhatsApp Web mostraba el boton pero no contaba como canal. Se pasan a un
# espacio comun antes de leer el numero; cualquier otro caracter sigue siendo
# texto que no se sabe leer.
_SEPARATOR_SPACES = re.compile(
    "[\t\n\v\f\r\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]"
)
# Lo unico que se acepta alrededor de los digitos (ASCII, como ``\d`` de JS):
# espacios y separadores, y un "+" al principio.
_ALLOWED_SHAPE = re.compile(r"\+?[0-9 \-().]+")
_NON_DIGITS = re.compile(r"[^0-9]")
# 11 (AMBA) es el unico codigo de area de dos digitos; el resto empieza con 2
# o 3.
_AREA_START = re.compile(r"^(11|[23])")


def _to_ten_digits(national: str) -> str | None:
    """Numero nacional (sin 0) a sus 10 digitos, sin el 15 de celular."""
    if not _AREA_START.match(national):
        return None
    if len(national) == _NATIONAL_LENGTH:
        return national
    if len(national) != _NATIONAL_WITH_15_LENGTH:
        return None
    area_lengths = (2,) if national.startswith("11") else (3, 4)
    for area in area_lengths:
        if national[area : area + 2] == "15":
            return national[:area] + national[area + 2 :]
    return None


def _from_argentine_international(after_country: str) -> str | None:
    """Lo que sigue al 54. Sin 9 ni 15 se respeta tal cual (linea fija con
    WhatsApp Business): agregarle el 9 la mandaria a otro numero."""
    is_mobile = after_country.startswith("9")
    rest = after_country[1:] if is_mobile else after_country
    if rest.startswith("0"):
        rest = rest[1:]
    national = _to_ten_digits(rest)
    if national is None:
        return None
    had_mobile_prefix = is_mobile or len(rest) == _NATIONAL_WITH_15_LENGTH
    return (_ARGENTINA_MOBILE if had_mobile_prefix else _ARGENTINA_CODE) + national


def _from_international(digits: str) -> str | None:
    if digits.startswith(_ARGENTINA_CODE):
        return _from_argentine_international(digits[len(_ARGENTINA_CODE) :])
    plausible = (
        not digits.startswith("0")
        and _MIN_INTERNATIONAL_LENGTH <= len(digits) <= _MAX_INTERNATIONAL_LENGTH
    )
    return digits if plausible else None


def normalize_phone_for_whatsapp(raw: str | None) -> str | None:
    """Telefono de texto libre -> numero para wa.me, o ``None`` si no se puede
    leer con confianza. Sin "+" ni "00" se asume Argentina, salvo que ya
    empiece con 54 y tenga el largo de un numero internacional."""
    trimmed = _SEPARATOR_SPACES.sub(" ", raw or "").strip(" ")
    if not trimmed or not _ALLOWED_SHAPE.fullmatch(trimmed):
        return None
    digits = _NON_DIGITS.sub("", trimmed)
    if trimmed.startswith("+"):
        return _from_international(digits)
    if digits.startswith("00"):
        return _from_international(digits[2:])
    if digits.startswith(_ARGENTINA_CODE) and len(digits) >= _NATIONAL_WITH_15_LENGTH:
        return _from_argentine_international(digits[len(_ARGENTINA_CODE) :])
    national = digits[1:] if digits.startswith("0") else digits
    ten_digits = _to_ten_digits(national)
    return _ARGENTINA_MOBILE + ten_digits if ten_digits else None
