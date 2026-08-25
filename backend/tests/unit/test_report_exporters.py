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

from modules.reports.exporter import export_to_csv, export_to_excel, export_to_pdf
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
            total_appointments=12,
            completed_appointments=8,
            cancelled_appointments=2,
            pending_appointments=1,
            confirmed_appointments=1,
            total_revenue=48500.5,
            average_ticket=6062.56,
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


def test_csv_incluye_los_datos_del_resumen() -> None:
    contenido = export_to_csv(_summary()).decode("utf-8-sig")
    assert "Corte clásico" in contenido
    assert "Ana Pérez" in contenido
    assert "48500.5" in contenido or "48500,5" in contenido


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
