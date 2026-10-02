"""El PDF del reporte se lee en castellano, con fechas e importes es-AR.

2026-10-02, QA en navegador: el PDF decia "Sena retenida", mostraba las
fechas del rango en ISO ("Desde: 2026-01-01"), el estado de cada turno crudo
("confirmed") y los importes como los imprime Python ("$1500.0"). Lo lee el
dueno, no una maquina: el CSV y el Excel siguen con las claves y los valores
crudos para la planilla del contador.
"""

import pytest

from modules.reports.exporter import export_to_pdf
from tests.unit.test_reporte_pdf_columnas import _espiar
from tests.unit.test_report_exporters import _summary


def _textos(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    trazos = _espiar(monkeypatch)
    resumen = _summary()
    resumen.appointments[0].status = "pending_payment"
    resumen.appointments[0].service_price = 1500.0
    export_to_pdf(resumen)
    return [t.texto for t in trazos]


def test_la_sena_retenida_lleva_enie(monkeypatch: pytest.MonkeyPatch) -> None:
    textos = _textos(monkeypatch)

    assert "Seña retenida: $ 3.500" in textos
    assert not any("Sena" in t for t in textos)


def test_las_fechas_del_rango_van_en_dd_mm_aaaa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    textos = _textos(monkeypatch)

    assert "Desde: 01/01/2026" in textos
    assert "Hasta: 31/01/2026" in textos


def test_los_importes_van_con_formato_es_ar(monkeypatch: pytest.MonkeyPatch) -> None:
    textos = _textos(monkeypatch)

    assert "Ingreso total: $ 48.500,50" in textos
    assert "Ticket promedio: $ 6.062,56" in textos
    assert "$ 1.500" in textos
    assert not any("1500.0" in t for t in textos)


def test_el_estado_del_turno_va_en_castellano(monkeypatch: pytest.MonkeyPatch) -> None:
    textos = _textos(monkeypatch)

    assert "Pendiente de pago" in textos
    assert "pending_payment" not in textos
