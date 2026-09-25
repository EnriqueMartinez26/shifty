"""El PDF del reporte dibuja cada turno en columnas y nunca pierde el precio.

2026-09-18, hallazgo B5-19: ``export_to_pdf`` armaba un solo string por turno
(``fecha | estado | servicio | profesional | cliente | $precio``) y lo cortaba
en ``line[:110]``. El precio es lo ultimo de la linea, asi que con nombres
largos era lo primero que desaparecia: el PDF mostraba turnos sin importe, en
silencio. Ademas el nombre del cliente llega de la reserva publica: un
caracter de control (NUL, bidi, zero-width; regla 19) viajaba tal cual al PDF.

Se espia el ``Canvas`` de reportlab para ver QUE se dibuja y DONDE, sin
depender de un parser de PDF.
"""

from dataclasses import dataclass
from typing import Any

import pytest
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from modules.reports.exporter import export_to_pdf
from tests.unit.test_report_exporters import _summary

ANCHO_A4 = 595.27
MARGEN = 40


@dataclass
class _Trazo:
    metodo: str
    x: float
    texto: str
    fuente: str
    tamano: float

    def borde_derecho(self) -> float:
        ancho = stringWidth(self.texto, self.fuente, self.tamano)
        return self.x if self.metodo == "drawRightString" else self.x + ancho


def _espiar(monkeypatch: pytest.MonkeyPatch) -> list[_Trazo]:
    trazos: list[_Trazo] = []
    for metodo in ("drawString", "drawRightString"):
        original = getattr(canvas.Canvas, metodo)

        def espia(
            self: canvas.Canvas,
            x: float,
            y: float,
            text: str,
            *args: Any,
            _metodo: str = metodo,
            _original: Any = original,
            **kwargs: Any,
        ) -> Any:
            trazos.append(_Trazo(_metodo, x, text, self._fontname, self._fontsize))
            return _original(self, x, y, text, *args, **kwargs)

        monkeypatch.setattr(canvas.Canvas, metodo, espia)
    return trazos


def test_con_nombres_largos_el_precio_sigue_en_el_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trazos = _espiar(monkeypatch)
    resumen = _summary()
    turno = resumen.appointments[0]
    turno.service_name = "Coloracion completa con tratamiento " * 4
    turno.staff_name = "Profesional de apellido muy largo " * 3
    turno.client_name = "Cliente con nombre larguisimo " * 5
    turno.service_price = 123456.78

    contenido = export_to_pdf(resumen)

    assert contenido[:5] == b"%PDF-"
    textos = [t.texto for t in trazos]
    assert "$123456.78" in textos
    # Los nombres se recortan con marca visible, no en silencio.
    assert any(t.startswith("Cliente con nombre") and t.endswith("...") for t in textos)
    # Nada se dibuja fuera del margen derecho de la hoja.
    assert max(t.borde_derecho() for t in trazos) <= ANCHO_A4 - MARGEN + 0.01


def test_el_pdf_no_dibuja_caracteres_de_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trazos = _espiar(monkeypatch)
    resumen = _summary()
    resumen.appointments[0].client_name = "Ana\x00 ‮P​erez\r\n"

    export_to_pdf(resumen)

    dibujado = "".join(t.texto for t in trazos)
    for control in ("\x00", "‮", "​", "\r", "\n"):
        assert control not in dibujado, repr(control)
    assert "Ana Perez" in [t.texto for t in trazos]
