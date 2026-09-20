import csv
import unicodedata
from io import BytesIO, StringIO
from datetime import datetime
from typing import Any

from core.utils import ARGENTINA_TZ, ensure_utc_aware
from modules.reports.schemas import ReportSummaryResponse

# Caracteres con los que Excel/Sheets arrancan una FORMULA. client_name lo
# controla un atacante anonimo via la reserva publica: una celda que empieza con
# alguno de estos puede exfiltrar datos o ejecutar DDE al abrir el export.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


# Toda hora que ve el dueno sale en hora argentina (regla 24, S-13). Antes el
# PDF formateaba el instante UTC sin zona (22:30 ART salia como 01:30 del dia
# siguiente) y CSV/Excel exportaban ISO UTC. Para las planillas se eligio hora
# local legible con la zona explicita en el encabezado de la columna.
_LOCAL_ZONE_LABEL = "America/Argentina/Buenos_Aires"
_STARTS_AT_HEADER = f"starts_at ({_LOCAL_ZONE_LABEL})"
_ENDS_AT_HEADER = f"ends_at ({_LOCAL_ZONE_LABEL})"


def _local_datetime(value: datetime) -> str:
    """``YYYY-MM-DD HH:MM`` en hora argentina; un naive se toma como UTC."""
    return ensure_utc_aware(value).astimezone(ARGENTINA_TZ).strftime("%Y-%m-%d %H:%M")


def _safe_text(value: object) -> str:
    """Texto sin caracteres de control (regla 19): NUL, saltos de linea, bidi,
    zero-width y BOM (categoria Unicode C*) no llegan a ningun exportador.

    AUD2-B5-03: la limpieza existia solo para el PDF. Un NUL en el nombre hacia
    que ``openpyxl`` levantara ``IllegalCharacterError`` —que no es
    ``RuntimeError``, lo unico que captura el router— y la descarga de Excel
    terminaba en un 500 opaco; en el CSV el bidi override viajaba intacto.
    """
    return "".join(
        char for char in str(value) if not unicodedata.category(char).startswith("C")
    ).strip()


def _neutralize_cell(value: object) -> object:
    """Celda de planilla: sin caracteres de control y con apostrofo delante si
    el texto empieza con un trigger de formula. Los no-texto pasan derecho."""
    if not isinstance(value, str):
        return value
    limpio = _safe_text(value)
    if limpio and limpio[0] in _FORMULA_TRIGGERS:
        return "'" + limpio
    return limpio


def _summary_metrics(
    summary: ReportSummaryResponse,
) -> tuple[tuple[str, str, object], ...]:
    """Metricas del encabezado: ``(clave, etiqueta, valor)``, una sola lista.

    AUD2-B5-13: estaba escrita tres veces —una por exportador— y por eso
    ``retained_deposit_revenue`` (B5-10) se agrego a la pantalla y a ninguno de
    los tres archivos. El dueno que baja el Excel para su contador no podia
    descomponer el total en ingreso por servicio y sena retenida. La clave es
    la que usan CSV y Excel; la etiqueta, la que dibuja el PDF.

    La lista tiene que cubrir TODOS los campos de ``ReportSummaryStats``: si
    falta uno, los contadores por estado del archivo no suman el total y el
    dueno ve en la planilla el mismo defecto que AUD2-B5-14 arreglo en la
    pantalla. Lo fija
    ``test_report_exporters.py::test_el_archivo_escribe_todos_los_contadores_del_resumen``,
    que compara estas claves contra ``ReportSummaryStats.model_fields``.
    """
    stats = summary.stats
    return (
        ("total_appointments", "Total turnos", stats.total_appointments),
        ("completed_appointments", "Completados", stats.completed_appointments),
        ("cancelled_appointments", "Cancelados", stats.cancelled_appointments),
        ("pending_appointments", "Pendientes", stats.pending_appointments),
        ("confirmed_appointments", "Confirmados", stats.confirmed_appointments),
        ("absent_appointments", "Ausentes", stats.absent_appointments),
        ("expired_appointments", "Vencidos", stats.expired_appointments),
        ("total_revenue", "Ingreso total", stats.total_revenue),
        ("average_ticket", "Ticket promedio", stats.average_ticket),
        ("retained_deposit_revenue", "Sena retenida", stats.retained_deposit_revenue),
    )


def export_to_csv(summary: ReportSummaryResponse) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["from_date", summary.from_date.isoformat()])
    writer.writerow(["to_date", summary.to_date.isoformat()])
    writer.writerow([])
    writer.writerow(["metric", "value"])
    for clave, _etiqueta, valor in _summary_metrics(summary):
        writer.writerow([clave, valor])
    writer.writerow([])

    writer.writerow(
        [
            "public_id",
            _STARTS_AT_HEADER,
            _ENDS_AT_HEADER,
            "status",
            "service_name",
            "staff_name",
            "client_name",
            "service_price",
        ]
    )

    for item in summary.appointments:
        writer.writerow(
            [
                item.public_id,
                _local_datetime(item.starts_at),
                _local_datetime(item.ends_at),
                _neutralize_cell(item.status),
                _neutralize_cell(item.service_name),
                _neutralize_cell(item.staff_name),
                _neutralize_cell(item.client_name),
                item.service_price,
            ]
        )

    # utf-8-sig antepone el BOM: sin el, Excel es-AR abre el CSV como ANSI y
    # los acentos salen rotos ("Corte clÃ¡sico"). B5-16.
    return buffer.getvalue().encode("utf-8-sig")


def export_to_excel(summary: ReportSummaryResponse) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("Falta dependencia openpyxl para exportar Excel") from exc

    wb = Workbook()
    summary_sheet = wb.active
    summary_sheet.title = "Summary"

    summary_sheet.append(["from_date", summary.from_date.isoformat()])
    summary_sheet.append(["to_date", summary.to_date.isoformat()])
    summary_sheet.append([])
    summary_sheet.append(["metric", "value"])
    for clave, _etiqueta, valor in _summary_metrics(summary):
        summary_sheet.append([clave, valor])

    appointments_sheet = wb.create_sheet(title="Appointments")
    appointments_sheet.append(
        [
            "public_id",
            _STARTS_AT_HEADER,
            _ENDS_AT_HEADER,
            "status",
            "service_name",
            "staff_name",
            "client_name",
            "service_price",
        ]
    )
    for item in summary.appointments:
        appointments_sheet.append(
            [
                item.public_id,
                _local_datetime(item.starts_at),
                _local_datetime(item.ends_at),
                _neutralize_cell(item.status),
                _neutralize_cell(item.service_name),
                _neutralize_cell(item.staff_name),
                _neutralize_cell(item.client_name),
                item.service_price,
            ]
        )

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()


# Columnas de la tabla de turnos del PDF (B5-19): (x, ancho) en puntos sobre
# A4 (595 pt, margenes de 40). Antes era un solo string cortado en 110
# caracteres y el precio, al final, era lo primero que se perdia. Ahora cada
# campo tiene su columna, los textos se recortan con "..." dentro de la suya y
# el precio va alineado a la derecha y nunca se recorta.
_PDF_FONT_SIZE = 8
_PDF_TEXT_COLUMNS = ((40, 68), (110, 66), (178, 106), (288, 88), (378, 108))
_PDF_PRICE_RIGHT_EDGE = 555
_PDF_HEADERS = ("Fecha", "Estado", "Servicio", "Profesional", "Cliente", "Precio")
_ELLIPSIS = "..."


def _fit_pdf_text(text: str, width: float, font: str, string_width: Any) -> str:
    """Recorta ``text`` para que entre en ``width`` puntos, marcando el corte."""
    if string_width(text, font, _PDF_FONT_SIZE) <= width:
        return text
    while text and string_width(text + _ELLIPSIS, font, _PDF_FONT_SIZE) > width:
        text = text[:-1]
    return text.rstrip() + _ELLIPSIS


def _draw_pdf_row(
    pdf: Any, y: float, cells: tuple[object, ...], *, font: str = "Helvetica"
) -> None:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    pdf.setFont(font, _PDF_FONT_SIZE)
    *texts, price = cells
    for (x, width), value in zip(_PDF_TEXT_COLUMNS, texts, strict=True):
        pdf.drawString(x, y, _fit_pdf_text(_safe_text(value), width, font, stringWidth))
    pdf.drawRightString(_PDF_PRICE_RIGHT_EDGE, y, _safe_text(price))


def export_to_pdf(summary: ReportSummaryResponse) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("Falta dependencia reportlab para exportar PDF") from exc

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    y = 800
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, "Reporte de Turnos")
    y -= 24

    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Desde: {summary.from_date.isoformat()}")
    y -= 14
    pdf.drawString(40, y, f"Hasta: {summary.to_date.isoformat()}")
    y -= 20

    for _clave, etiqueta, valor in _summary_metrics(summary):
        pdf.drawString(40, y, f"{etiqueta}: {valor}")
        y -= 14

    y -= 8
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(40, y, "Turnos")
    y -= 16
    _draw_pdf_row(pdf, y, _PDF_HEADERS, font="Helvetica-Bold")
    y -= 12

    for item in summary.appointments:
        cells = (
            _local_datetime(item.starts_at),
            item.status,
            item.service_name,
            item.staff_name,
            item.client_name,
            f"${item.service_price}",
        )
        _draw_pdf_row(pdf, y, cells)
        y -= 11
        if y < 40:
            pdf.showPage()
            y = 800

    pdf.save()
    buffer.seek(0)
    return buffer.read()
