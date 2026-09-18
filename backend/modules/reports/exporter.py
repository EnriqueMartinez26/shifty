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


def _neutralize_cell(value: object) -> object:
    """Prefija con apostrofo el texto que empieza con un trigger de formula."""
    if isinstance(value, str) and value and value[0] in _FORMULA_TRIGGERS:
        return "'" + value
    return value


def export_to_csv(summary: ReportSummaryResponse) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["from_date", summary.from_date.isoformat()])
    writer.writerow(["to_date", summary.to_date.isoformat()])
    writer.writerow([])
    writer.writerow(["metric", "value"])
    writer.writerow(["total_appointments", summary.stats.total_appointments])
    writer.writerow(["completed_appointments", summary.stats.completed_appointments])
    writer.writerow(["cancelled_appointments", summary.stats.cancelled_appointments])
    writer.writerow(["pending_appointments", summary.stats.pending_appointments])
    writer.writerow(["confirmed_appointments", summary.stats.confirmed_appointments])
    writer.writerow(["total_revenue", summary.stats.total_revenue])
    writer.writerow(["average_ticket", summary.stats.average_ticket])
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
    summary_sheet.append(["total_appointments", summary.stats.total_appointments])
    summary_sheet.append(
        ["completed_appointments", summary.stats.completed_appointments]
    )
    summary_sheet.append(
        ["cancelled_appointments", summary.stats.cancelled_appointments]
    )
    summary_sheet.append(["pending_appointments", summary.stats.pending_appointments])
    summary_sheet.append(
        ["confirmed_appointments", summary.stats.confirmed_appointments]
    )
    summary_sheet.append(["total_revenue", summary.stats.total_revenue])
    summary_sheet.append(["average_ticket", summary.stats.average_ticket])

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


def _pdf_text(value: object) -> str:
    """Texto sin caracteres de control (regla 19): NUL, saltos de linea, bidi,
    zero-width y BOM (categoria Unicode C*) no llegan al PDF."""
    return "".join(
        char for char in str(value) if not unicodedata.category(char).startswith("C")
    ).strip()


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
        pdf.drawString(x, y, _fit_pdf_text(_pdf_text(value), width, font, stringWidth))
    pdf.drawRightString(_PDF_PRICE_RIGHT_EDGE, y, _pdf_text(price))


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

    metrics = [
        ("Total turnos", summary.stats.total_appointments),
        ("Completados", summary.stats.completed_appointments),
        ("Cancelados", summary.stats.cancelled_appointments),
        ("Pendientes", summary.stats.pending_appointments),
        ("Confirmados", summary.stats.confirmed_appointments),
        ("Ingreso total", summary.stats.total_revenue),
        ("Ticket promedio", summary.stats.average_ticket),
    ]

    for label, value in metrics:
        pdf.drawString(40, y, f"{label}: {value}")
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
