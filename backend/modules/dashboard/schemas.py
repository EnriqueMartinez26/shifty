from datetime import datetime
from pydantic import BaseModel


class DashboardStatSummary(BaseModel):
    appointments_today: int
    pending_confirmations: int
    occupancy_rate: float  # Porcentaje de tiempo ocupado hoy
    new_clients_last_30d: int
    weekly_revenue: float
    revenue_trend: float  # Porcentaje vs semana anterior
    average_appointment_minutes: int


class UpcomingAppointmentItem(BaseModel):
    public_id: str
    starts_at: datetime
    status: str
    service_name: str
    staff_name: str
    client_name: str


class DashboardSummaryResponse(BaseModel):
    stats: DashboardStatSummary
    upcoming_appointments: list[UpcomingAppointmentItem]
