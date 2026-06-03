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


class ReportClientStats(BaseModel):
    total_clients: int
    new_clients: int
    returning_clients: int
    inactive_clients: int


class ReportTopServiceItem(BaseModel):
    service_id: str
    service_name: str
    appointments: int
    completed_appointments: int
    revenue: float


class ReportTopClientItem(BaseModel):
    client_id: str
    client_name: str
    appointments: int
    completed_appointments: int
    revenue: float


class ReportDebtClientItem(BaseModel):
    client_id: str
    client_name: str
    balance: float


class ReportDebtSummary(BaseModel):
    outstanding_balance: float
    debtors_count: int
    average_debt: float
    top_debtors: list[ReportDebtClientItem] = Field(default_factory=list)


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
    client_stats: ReportClientStats
    top_services: list[ReportTopServiceItem] = Field(default_factory=list)
    top_clients: list[ReportTopClientItem] = Field(default_factory=list)
    debt_summary: ReportDebtSummary
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
