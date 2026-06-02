from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from core.validation import SAFE_FILENAME_PREFIX_PATTERN


ExportFormat = Literal["csv", "excel", "pdf"]


class ReportQueryParams(BaseModel):
    from_date: date | None = None
    to_date: date | None = None


class ReportSummaryStats(BaseModel):
    total_appointments: int
    completed_appointments: int
    cancelled_appointments: int
    pending_appointments: int
    confirmed_appointments: int
    total_revenue: float
    average_ticket: float


class ReportAppointmentItem(BaseModel):
    public_id: str
    starts_at: datetime
    ends_at: datetime
    status: str
    service_name: str
    staff_name: str
    client_name: str
    service_price: float


class ReportSummaryResponse(BaseModel):
    from_date: date
    to_date: date
    stats: ReportSummaryStats
    appointments: list[ReportAppointmentItem]


class ProfessionalReportItem(BaseModel):
    staff_id: str
    staff_name: str
    appointments: int
    completed_appointments: int
    confirmed_appointments: int
    absent_appointments: int
    cancelled_appointments: int
    used_minutes: int
    used_hours: float
    available_minutes: int
    available_hours: float
    blocked_minutes: int
    blocked_hours: float
    occupancy_rate: float
    revenue: float


class ProfessionalReportsResponse(BaseModel):
    from_date: date
    to_date: date
    professionals: list[ProfessionalReportItem]


class ReportExportRequest(BaseModel):
    format: ExportFormat
    from_date: date | None = None
    to_date: date | None = None
    filename_prefix: str = Field(
        default="reporte-turnos",
        min_length=3,
        max_length=50,
        pattern=SAFE_FILENAME_PREFIX_PATTERN,
    )
