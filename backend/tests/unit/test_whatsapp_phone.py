"""El WhatsApp de la tienda se lee con la misma regla que el front.

2026-10-03, decision de Mateo: una sena obligatoria se paga por Mercado Pago o
por WhatsApp, y una tienda que pide una sena obligatoria tiene que tener al
menos uno de los dos canales. El backend decide si el WhatsApp de la tienda
sirve con el mismo criterio que arma el link de wa.me en el front
(``frontend/src/shared/utils/whatsAppPhone.ts``): un numero que el front no
puede convertir en link no es un canal, porque el cliente no veria el boton.

Los casos son los de ``whatsAppPhone.test.ts``; si cambia uno, cambia el otro.
"""

from __future__ import annotations

import pytest

from core.whatsapp_phone import normalize_phone_for_whatsapp


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("11 5555 0000", "5491155550000"),
        ("011 15-5555-0000", "5491155550000"),
        ("+54 9 11 5555 0000", "5491155550000"),
        ("5491155550000", "5491155550000"),
        ("351 555-1234", "5493515551234"),
        ("0351 15 555 1234", "5493515551234"),
        ("(011) 5555-0000", "5491155550000"),
        ("+54 9 11 15 5555 0000", "5491155550000"),
        ("+54 11 15 5555 0000", "5491155550000"),
        ("00 54 9 351 555 1234", "5493515551234"),
        ("2964 15 401234", "5492964401234"),
        ("02964 401234", "5492964401234"),
    ],
)
def test_normaliza_telefonos_argentinos(raw: str, expected: str) -> None:
    assert normalize_phone_for_whatsapp(raw) == expected


def test_con_54_escrito_y_sin_9_ni_15_lo_respeta_tal_cual() -> None:
    assert normalize_phone_for_whatsapp("+54 11 4555 0000") == "541145550000"
    assert normalize_phone_for_whatsapp("541145550000") == "541145550000"
    assert normalize_phone_for_whatsapp("+54 011 4555 0000") == "541145550000"


def test_respeta_un_numero_que_ya_trae_otro_codigo_de_pais() -> None:
    assert normalize_phone_for_whatsapp("+1 (202) 555-0123") == "12025550123"
    assert normalize_phone_for_whatsapp("0034 612 345 678") == "34612345678"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "llamame al local",
        "123",
        "4555-1234",
        "011 5555 0000 1234 5678",
        "9 11 5555 0000",
        "+12 345",
        "11 +5555 0000",
        None,
    ],
)
def test_sin_confianza_devuelve_none(raw: str | None) -> None:
    assert normalize_phone_for_whatsapp(raw) is None
