from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from core.validation import PUBLIC_ID_PATTERN
from modules.appointments.model import AppointmentStatus


# ---------------------------------------------------------------------------
# Crear turno
# ---------------------------------------------------------------------------

class AppointmentCreate(BaseModel):
    service_id:      str = Field(..., min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
    staff_id:        str = Field(..., min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
    starts_at:       datetime
    notes:           Optional[str] = Field(None, max_length=1000)
    idempotency_key: str = Field(..., min_length=10, max_length=128)

    @model_validator(mode="after")
    def starts_at_must_be_future(self) -> "AppointmentCreate":
        from core.utils import now_utc
        val = self.starts_at
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        if val <= now_utc():
            raise ValueError("No se puede agendar un turno en el pasado.")
        return self


# ---------------------------------------------------------------------------
# Respuesta de turno (enriquecida con nuevos campos de la spec)
# ---------------------------------------------------------------------------

class AppointmentResponse(BaseModel):
    public_id:    str
    service_id:   str
    staff_id:     str
    starts_at:    datetime
    ends_at:      datetime
    status:       str
    notes:        Optional[str] = None
    notes_staff:  Optional[str] = None   # Notas del profesional (nuevo)
    intake_answers: Dict[str, str] = Field(default_factory=dict)
    cancelled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AppointmentListItem(BaseModel):
    public_id:   str
    service_id:  str
    service_name: str
    staff_id:    str
    client_name: str
    starts_at:   datetime
    ends_at:     datetime
    status:      str
    notes:       Optional[str] = None
    notes_staff: Optional[str] = None
    intake_answers: Dict[str, str] = Field(default_factory=dict)



# ---------------------------------------------------------------------------
# Actualizar notas del profesional
# ---------------------------------------------------------------------------

class AppointmentNotesStaffUpdate(BaseModel):
    """Permite al staff agregar o editar sus notas sobre el turno."""
    notes_staff: str = Field(..., max_length=1000)


# ---------------------------------------------------------------------------
# Reprogramar turno
# ---------------------------------------------------------------------------

class AppointmentReschedule(BaseModel):
    """Body para reprogramar un turno a una nueva fecha/hora."""
    new_starts_at:   datetime
    idempotency_key: str = Field(..., min_length=10, max_length=128)

    @model_validator(mode="after")
    def new_date_must_be_future(self) -> "AppointmentReschedule":
        from core.utils import now_utc
        val = self.new_starts_at
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        if val <= now_utc():
            raise ValueError("La nueva fecha debe ser en el futuro.")
        return self


# ---------------------------------------------------------------------------
# Filtros de búsqueda avanzada
# ---------------------------------------------------------------------------

class AppointmentFilterParams(BaseModel):
    """
    Filtros dinámicos: solo se aplican los que estén presentes.
    """
    client_name: Optional[str]       = Field(None, max_length=100)
    staff_id:    Optional[str]       = Field(None, max_length=64, pattern=PUBLIC_ID_PATTERN)
    service_id:  Optional[str]       = Field(None, max_length=64, pattern=PUBLIC_ID_PATTERN)
    statuses:    Optional[List[str]] = Field(None, max_length=10)
    from_date:   Optional[date]      = None
    to_date:     Optional[date]      = None
    page:        int = Field(default=1, ge=1)
    page_size:   int = Field(default=20, ge=1, le=100)


class AppointmentSearchResult(BaseModel):
    """Respuesta enriquecida con nombres resueltos para la UI."""
    public_id:    str
    starts_at:    datetime
    ends_at:      datetime
    status:       str
    notes:        Optional[str] = None
    notes_staff:  Optional[str] = None
    intake_answers: Dict[str, str] = Field(default_factory=dict)
    cancelled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    service_name: str
    service_id:   str
    staff_name:   str
    staff_id:     str
    client_name:  str
    client_id:    str


class AppointmentSearchResponse(BaseModel):
    total:     int
    page:      int
    page_size: int
    results:   List[AppointmentSearchResult]
