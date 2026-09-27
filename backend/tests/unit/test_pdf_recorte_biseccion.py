"""El recorte de texto del PDF mide por biseccion, no caracter por caracter.

2026-09-24, F1-07 (R8-06): ``_fit_pdf_text`` sacaba un caracter por vuelta y
medía el texto entero con ``stringWidth`` cada vez: O(n^2) sobre el largo del
nombre, por celda y por fila. Un nombre de miles de caracteres (lo controla un
anonimo en la reserva publica) eran miles de mediciones. Por biseccion son
O(log n) mediciones y el resultado es el mismo.
"""

from __future__ import annotations

import pytest
from reportlab.pdfbase.pdfmetrics import stringWidth

from modules.reports.exporter import _ELLIPSIS, _PDF_FONT_SIZE, _fit_pdf_text


def _recorte_de_referencia(text: str, width: float, font: str) -> str:
    """El algoritmo anterior, lineal: la verdad contra la que se compara."""
    if stringWidth(text, font, _PDF_FONT_SIZE) <= width:
        return text
    while text and stringWidth(text + _ELLIPSIS, font, _PDF_FONT_SIZE) > width:
        text = text[:-1]
    return text.rstrip() + _ELLIPSIS


@pytest.mark.parametrize(
    "texto",
    [
        "",
        "Ana",
        "Corte clasico con barba",
        "Nombre   con espacios   al corte de la columna",
        "W" * 40,
        "i" * 200,
        "Maria Jose de los Angeles Fernandez Gutierrez",
    ],
)
@pytest.mark.parametrize("ancho", [10.0, 66.0, 108.0])
def test_la_biseccion_recorta_igual_que_el_algoritmo_lineal(
    texto: str, ancho: float
) -> None:
    assert _fit_pdf_text(texto, ancho, "Helvetica", stringWidth) == (
        _recorte_de_referencia(texto, ancho, "Helvetica")
    )


def test_un_nombre_larguisimo_se_mide_pocas_veces() -> None:
    mediciones = 0

    def medir(text: str, font: str, size: float) -> float:
        nonlocal mediciones
        mediciones += 1
        return float(stringWidth(text, font, size))

    texto = "Nombre larguisimo " * 1_000  # 18.000 caracteres
    recortado = _fit_pdf_text(texto, 108.0, "Helvetica", medir)

    assert recortado.endswith(_ELLIPSIS)
    assert stringWidth(recortado, "Helvetica", _PDF_FONT_SIZE) <= 108.0
    # log2(18.000) ~ 15: con margen, nunca del orden del largo.
    assert mediciones <= 20, mediciones
