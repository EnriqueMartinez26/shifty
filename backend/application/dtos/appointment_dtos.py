from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class CreateAppointmentRequest(BaseModel):
    service_id: str
    staff_id: str
    start_time: datetime
    duration_minutes: int
    client_name: str
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    notes: Optional[str] = None
    idempotency_key: Optional[str] = None

class AppointmentResponse(BaseModel):
    id: str
    service_id: str
    staff_id: str
    store_id: str
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    client_name: str
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    status: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
