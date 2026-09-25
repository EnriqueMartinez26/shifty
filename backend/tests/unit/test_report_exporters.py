"""Exportadores de reportes: CSV, Excel y PDF.

Son el camino menos probado del sistema y el que mas facil se rompe en
silencio: generan bytes binarios, asi que un fallo no se nota hasta que
alguien abre el archivo. Estos tests verifican que cada formato produzca un
documento valido y que los datos del resumen efectivamente aparezcan.
"""

from datetime import date, datetime, timedelta, timezone
import io
import zipfile

import pytest

from modules.reports.exporter import (
    _summary_metrics,
    export_to_csv,
    export_to_excel,
    export_to_pdf,
)
from modules.reports.schemas import (
    ReportAppointmentItem,
    ReportClientStats,
    ReportDebtClientItem,
    ReportDebtSummary,
    ReportSummaryResponse,
    ReportSummaryStats,
    ReportTopClientItem,
    ReportTopServiceItem,
)


def _summary(*, con_datos: bool = True) -> ReportSummaryResponse:
    inicio = datetime.now(timezone.utc)
    return ReportSummaryResponse(
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 31),
        stats=ReportSummaryStats(
            # Los cinco contadores clasicos mas absent y expired suman el
            # total (AUD2-B5-14): 8+2+1+1+1+1 = 14.
            total_appointments=14,
            completed_appointments=8,
            cancelled_appointments=2,
            pending_appointments=1,
            confirmed_appointments=1,
            total_revenue=48500.5,
            average_ticket=6062.56,
            retained_deposit_revenue=3500.0,
            absent_appointments=1,
            expired_appointments=1,
        ),
        client_stats=ReportClientStats(
            total_clients=9, new_clients=4, returning_clients=5, inactive_clients=1
        ),
        top_services=[
            ReportTopServiceItem(
                service_id="svc-1",
                service_name="Corte clásico",
                appointments=6,
                completed_appointments=5,
                revenue=30000.0,
            )
        ]
        if con_datos
        else [],
        top_clients=[
            ReportTopClientItem(
                client_id="cli-1",
                client_name="Ana Pérez",
                appointments=3,
                completed_appointments=3,
                revenue=18000.0,
            )
        ]
        if con_datos
        else [],
        debt_summary=ReportDebtSummary(
            outstanding_balance=5200.0,
            debtors_count=2,
            average_debt=2600.0,
            top_debtors=[
                ReportDebtClientItem(
                    client_id="cli-2", client_name="Juan Gómez", balance=5200.0
                )
            ]
            if con_datos
            else [],
        ),
        appointments=[
            ReportAppointmentItem(
                public_id="appt-1",
                starts_at=inicio,
                ends_at=inicio + timedelta(minutes=30),
                status="completed",
                service_name="Corte clásico",
                staff_name="Pro Demo",
                client_name="Ana Pérez",
                service_price=6000.0,
            )
        ]
        if con_datos
        else [],
    )


BOM_UTF8 = b"\xef\xbb\xbf"


def _csv_texto(resumen: ReportSummaryResponse) -> str:
    """Decodifica el CSV exigiendo el BOM y UTF-8 estricto en el resto.

    2026-09-18, hallazgo B5-16: el CSV salia sin BOM y estos tests lo
    decodificaban con ``utf-8-sig``, que acepta bytes CON o SIN BOM, asi que
    pasaban igual. Sin BOM, Excel es-AR abre el archivo como ANSI y el dueno ve
    ``Corte clÃ¡sico``.
    """
    contenido = export_to_csv(resumen)
    assert contenido[:3] == BOM_UTF8, "el CSV no arranca con el BOM de UTF-8"
    cuerpo = contenido[3:]
    assert BOM_UTF8 not in cuerpo, "el BOM va una sola vez, al inicio"
    return cuerpo.decode("utf-8")


def test_csv_incluye_los_datos_del_resumen() -> None:
    contenido = _csv_texto(_summary())
    assert contenido.startswith("from_date,2026-01-01")
    assert "Corte clásico" in contenido
    assert "Ana Pérez" in contenido
    assert "48500.5" in contenido or "48500,5" in contenido


def test_csv_neutraliza_inyeccion_de_formula() -> None:
    # client_name lo controla un atacante via la reserva publica.
    resumen = _summary()
    resumen.appointments[0].client_name = "=cmd|'/c calc'!A1"
    resumen.appointments[0].service_name = "+SUM(1+1)"
    contenido = _csv_texto(resumen)
    # La celda peligrosa queda prefijada con apostrofo, no arranca con =/+.
    assert "'=cmd" in contenido
    assert "'+SUM(1+1)" in contenido
    assert ",=cmd" not in contenido


def test_excel_produce_un_xlsx_valido() -> None:
    """Un .xlsx es un ZIP: si no abre, el archivo esta corrupto."""
    contenido = export_to_excel(_summary())
    assert contenido[:2] == b"PK", "no tiene la firma de un archivo ZIP/XLSX"
    with zipfile.ZipFile(io.BytesIO(contenido)) as libro:
        nombres = libro.namelist()
    assert any(n.startswith("xl/") for n in nombres)


def test_pdf_produce_un_documento_valido() -> None:
    contenido = export_to_pdf(_summary())
    assert contenido[:5] == b"%PDF-", "no tiene la cabecera de un PDF"
    assert b"%%EOF" in contenido[-2048:], "el PDF quedo truncado"


@pytest.mark.parametrize("exportador", [export_to_csv, export_to_excel, export_to_pdf])
def test_los_exportadores_toleran_un_reporte_vacio(exportador) -> None:  # type: ignore[no-untyped-def]
    """Un periodo sin actividad no puede romper la descarga."""
    contenido = exportador(_summary(con_datos=False))
    assert isinstance(contenido, bytes) and contenido


# 2026-09-20, AUD2-B5-03: un nombre con NUL/bidi/zero-width entraba crudo a las
# planillas. Sintoma: ``openpyxl`` levantaba ``IllegalCharacterError`` (que no
# es ``RuntimeError``, lo unico que captura el router), asi que la descarga de
# Excel del dueno terminaba en un 500 opaco; y en el CSV el ``U+202E`` viajaba
# intacto y daba vuelta el texto de la celda. La limpieza existia solo para el
# PDF. El dato es el mismo de ``test_el_pdf_no_dibuja_caracteres_de_control``.
_TEXTO_HOSTIL = "Ana\x00 ‮P​erez\r\n"
_CONTROL_PROHIBIDOS = ("\x00", "‮", "​", "\r", "\n")


def _texto_del_xlsx(contenido: bytes) -> str:
    """Las celdas de las hojas del libro (openpyxl las escribe inline).

    Se miran solo las hojas: el resto del ZIP (tema, estilos) trae saltos de
    linea propios de openpyxl que no son datos del reporte.
    """
    with zipfile.ZipFile(io.BytesIO(contenido)) as libro:
        return "".join(
            libro.read(nombre).decode("utf-8")
            for nombre in libro.namelist()
            if nombre.startswith("xl/worksheets/")
        )


def test_el_excel_no_se_cae_con_un_nombre_con_caracteres_de_control() -> None:
    resumen = _summary()
    resumen.appointments[0].client_name = _TEXTO_HOSTIL
    contenido = export_to_excel(resumen)
    assert contenido[:2] == b"PK"
    texto = _texto_del_xlsx(contenido)
    for prohibido in _CONTROL_PROHIBIDOS:
        assert prohibido not in texto, f"el Excel se llevo {prohibido!r}"
    assert "Ana Perez" in texto


def test_el_csv_no_se_lleva_el_bidi_ni_el_nul() -> None:
    resumen = _summary()
    resumen.appointments[0].client_name = _TEXTO_HOSTIL
    texto = _csv_texto(resumen)
    for prohibido in ("\x00", "‮", "​"):
        assert prohibido not in texto, f"el CSV se llevo {prohibido!r}"
    assert "Ana Perez" in texto


def test_excel_neutraliza_inyeccion_de_formula() -> None:
    """La proteccion de formula que ya tenia el CSV tambien vale para el Excel."""
    resumen = _summary()
    resumen.appointments[0].client_name = "=cmd|'/c calc'!A1"
    resumen.appointments[0].service_name = "+SUM(1+1)"
    texto = _texto_del_xlsx(export_to_excel(resumen))
    assert "&#39;=cmd" in texto or "'=cmd" in texto
    assert "&#39;+SUM(1+1)" in texto or "'+SUM(1+1)" in texto


# 2026-09-20, AUD2-B5-13: el campo retained_deposit_revenue (B5-10) se ve en
# pantalla pero no estaba en ninguno de los tres archivos. Sintoma: el dueno
# baja el Excel para su contador y la plata de senas retenidas no aparece, asi
# que el total del archivo no se puede descomponer en "ingreso por servicio" y
# "sena retenida" como si se puede en el panel.
def test_los_tres_exportadores_escriben_la_sena_retenida() -> None:
    resumen = _summary()
    assert "retained_deposit_revenue,3500.0" in _csv_texto(resumen)
    texto_excel = _texto_del_xlsx(export_to_excel(resumen))
    assert "retained_deposit_revenue" in texto_excel
    assert "3500" in texto_excel
    pdf = export_to_pdf(resumen)
    assert pdf[:5] == b"%PDF-"


# V-diff AUD2-B5-13/B5-14: `_summary_metrics` es una lista escrita a mano, asi
# que un contador nuevo en el schema no llega al archivo salvo que alguien se
# acuerde de agregarlo — exactamente lo que paso con retained_deposit_revenue
# (B5-10) y despues con absent/expired (B5-14). Sintoma para el dueno: los
# contadores por estado del archivo no suman el total, el mismo defecto que
# B5-14 arreglo en la pantalla. Este test ata las dos puntas: si manana se
# agrega un campo a ReportSummaryStats y no se escribe, falla aca.
def test_el_archivo_escribe_todos_los_contadores_del_resumen() -> None:
    claves = tuple(clave for clave, _etiqueta, _valor in _summary_metrics(_summary()))
    assert set(claves) == set(ReportSummaryStats.model_fields)
    assert len(claves) == len(set(claves)), "clave repetida en el encabezado"


def test_los_ausentes_y_los_vencidos_llegan_a_los_tres_archivos() -> None:
    resumen = _summary()
    csv_texto = _csv_texto(resumen)
    assert "absent_appointments,1" in csv_texto
    assert "expired_appointments,1" in csv_texto

    texto_excel = _texto_del_xlsx(export_to_excel(resumen))
    assert "absent_appointments" in texto_excel
    assert "expired_appointments" in texto_excel

    # El PDF dibuja la etiqueta, no la clave.
    etiquetas = {etiqueta for _clave, etiqueta, _valor in _summary_metrics(resumen)}
    assert {"Ausentes", "Vencidos"} <= etiquetas
    assert export_to_pdf(resumen)[:5] == b"%PDF-"
