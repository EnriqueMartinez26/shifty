from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.validation import SAFE_FILENAME_PREFIX_PATTERN


ExportFormat = Literal["csv", "excel", "pdf"]


class ReportSummaryStats(BaseModel):
    total_appointments: int
    completed_appointments: int
    cancelled_appointments: int
    pending_appointments: int
    confirmed_appointments: int
    total_revenue: float
    average_ticket: float
    # B5-10: parte de total_revenue que es sena retenida de turnos cancelados
    # (plata acreditada, no reembolsada). No es ingreso por servicio: ese es
    # total_revenue - retained_deposit_revenue. Aditivo, con default para no
    # romper a quien arma el DTO sin el.
    retained_deposit_revenue: float = 0.0


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
    # AUD2-B5-01: ``appointments`` es una pagina; esto dice si quedan mas
    # (y con ``stats.total_appointments``, cuantas en total). Aditivo.
    has_more: bool = False


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


class ReportTrendPoint(BaseModel):
    month: str
    total_appointments: int
    completed_appointments: int
    cancelled_appointments: int


class ReportTrendResponse(BaseModel):
    points: list[ReportTrendPoint] = Field(default_factory=list)


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


class AuditLogItem(BaseModel):
    """Una entrada de la auditoria de turnos y bloqueos de la tienda (B5-12).

    Sin ``context`` ni ids internos del actor: lo que ya ve un admin en el
    panel (quien, que turno, que cambio).
    """

    id: str
    created_at: datetime
    actor_email: str | None
    resource_type: str
    resource_id: str
    action: str
    payload_before: dict[str, Any] | list[Any] | str | int | float | bool | None
    payload_after: dict[str, Any] | list[Any] | str | int | float | bool | None
