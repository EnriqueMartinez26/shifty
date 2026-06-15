import csv
from io import BytesIO, StringIO

from modules.reports.schemas import ReportSummaryResponse


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
            "starts_at",
            "ends_at",
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
                item.starts_at.isoformat(),
                item.ends_at.isoformat(),
                item.status,
                item.service_name,
                item.staff_name,
                item.client_name,
                item.service_price,
            ]
        )

    return buffer.getvalue().encode("utf-8")


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
            "starts_at",
            "ends_at",
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
                item.starts_at.isoformat(),
                item.ends_at.isoformat(),
                item.status,
                item.service_name,
                item.staff_name,
                item.client_name,
                item.service_price,
            ]
        )

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()


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
    pdf.setFont("Helvetica", 8)

    for item in summary.appointments:
        line = (
            f"{item.starts_at.strftime('%Y-%m-%d %H:%M')} | {item.status} | "
            f"{item.service_name} | {item.staff_name} | {item.client_name} | ${item.service_price}"
        )
        pdf.drawString(40, y, line[:110])
        y -= 11
        if y < 40:
            pdf.showPage()
            pdf.setFont("Helvetica", 8)
            y = 800

    pdf.save()
    buffer.seek(0)
    return buffer.read()
