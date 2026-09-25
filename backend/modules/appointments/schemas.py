from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from core.validation import (
    PUBLIC_ID_PATTERN,
    normalize_client_phone,
    reject_payload_control_chars,
)
from modules.appointments.model import AppointmentStatus


# ---------------------------------------------------------------------------
# Crear turno
# ---------------------------------------------------------------------------


# Un turno cargado desde el panel para un cliente puede empezar hasta 5
# minutos antes del request: el dueno carga a quien acaba de sentarse (FF-04).
PANEL_BOOKING_PAST_GRACE = timedelta(minutes=5)


class AppointmentCreate(BaseModel):
    """Alta desde el panel. Dos formas, segun venga o no el cliente:

    - Sin ``client_phone`` (la de siempre): auto-turno a nombre de quien
      llama; ``staff_id`` obligatorio y ``starts_at`` en el futuro.
    - Con ``client_name`` + ``client_phone`` (FF-04, 2026-09-24, aditivo): turno
      para ese cliente de la tienda. ``staff_id`` opcional (se elige uno que
      atienda), ``starts_at`` hasta ``PANEL_BOOKING_PAST_GRACE`` en el pasado,
      ``allow_outside_schedule`` solo para el admin.
    """

    service_id: str = Field(..., min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
    staff_id: Optional[str] = Field(
        None, min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN
    )
    starts_at: datetime
    notes: Optional[str] = Field(None, max_length=1000)
    idempotency_key: str = Field(..., min_length=10, max_length=128)
    client_name: Optional[str] = Field(None, min_length=1, max_length=100)
    client_phone: Optional[str] = Field(None, min_length=6, max_length=30)
    client_email: Optional[EmailStr] = Field(None, max_length=255)
    allow_outside_schedule: bool = False

    @property
    def for_client(self) -> bool:
        return self.client_phone is not None

    @field_validator("client_phone")
    @classmethod
    def phone_must_be_numeric(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else normalize_client_phone(value)

    @model_validator(mode="after")
    def client_fields_go_together(self) -> "AppointmentCreate":
        if self.for_client:
            if self.client_name is None:
                raise ValueError("Falta el nombre del cliente.")
            return self
        if (
            self.client_name is not None
            or self.client_email is not None
            or self.allow_outside_schedule
        ):
            raise ValueError("Falta el telefono del cliente.")
        if self.staff_id is None:
            raise ValueError("Falta el profesional.")
        return self

    @model_validator(mode="after")
    def starts_at_must_be_future(self) -> "AppointmentCreate":
        from core.utils import now_utc

        val = self.starts_at
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        limite = now_utc()
        if self.for_client:
            limite -= PANEL_BOOKING_PAST_GRACE
        if val <= limite:
            raise ValueError("No se puede agendar un turno en el pasado.")
        return self

    @model_validator(mode="after")
    def reject_control_chars_in_notes(self) -> "AppointmentCreate":
        self.notes = reject_payload_control_chars(self.notes)
        self.client_name = reject_payload_control_chars(self.client_name)
        return self


# ---------------------------------------------------------------------------
# Respuesta de turno (enriquecida con nuevos campos de la spec)
# ---------------------------------------------------------------------------


class AppointmentResponse(BaseModel):
    public_id: str
    service_id: str
    staff_id: str
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    notes: Optional[str] = None
    notes_staff: Optional[str] = None  # Notas del profesional (nuevo)
    intake_answers: Dict[str, str] = Field(default_factory=dict)
    cancelled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AppointmentListItem(BaseModel):
    public_id: str
    service_id: str
    service_name: str
    staff_id: str
    # El repo joinea Staff pero el DTO nunca exponia el nombre: la agenda del dia
    # mostraba al cliente sin indicar el profesional (search si lo traia).
    staff_name: str
    client_name: str
    # Solo para administradores (dato personal); el resto del personal recibe
    # nulo. Sirve para el boton "mandar por WhatsApp" de la agenda.
    client_phone: Optional[str] = None
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    notes: Optional[str] = None
    notes_staff: Optional[str] = None
    intake_answers: Dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Actualizar notas del profesional
# ---------------------------------------------------------------------------


class AppointmentNotesStaffUpdate(BaseModel):
    """Permite al staff agregar o editar sus notas sobre el turno."""

    notes_staff: str = Field(..., max_length=1000)

    @model_validator(mode="after")
    def reject_control_chars_in_notes(self) -> "AppointmentNotesStaffUpdate":
        self.notes_staff = reject_payload_control_chars(self.notes_staff)
        return self


# ---------------------------------------------------------------------------
# Reprogramar turno
# ---------------------------------------------------------------------------


class AppointmentReschedule(BaseModel):
    """Body para reprogramar un turno a una nueva fecha/hora."""

    new_starts_at: datetime
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

    client_name: Optional[str] = Field(None, max_length=100)
    staff_id: Optional[str] = Field(None, max_length=64, pattern=PUBLIC_ID_PATTERN)
    service_id: Optional[str] = Field(None, max_length=64, pattern=PUBLIC_ID_PATTERN)
    statuses: Optional[List[str]] = Field(None, max_length=10)
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=20, ge=1, le=100)


class AppointmentSearchResult(BaseModel):
    """Respuesta enriquecida con nombres resueltos para la UI."""

    public_id: str
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    notes: Optional[str] = None
    notes_staff: Optional[str] = None
    intake_answers: Dict[str, str] = Field(default_factory=dict)
    cancelled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    service_name: str
    service_id: str
    staff_name: str
    staff_id: str
    client_name: str
    client_id: str
    client_phone: Optional[str] = None


class AppointmentSearchResponse(BaseModel):
    # ``None`` solo si el llamador pidio ``include_total=false`` (F3-06).
    total: Optional[int]
    page: int
    page_size: int
    results: List[AppointmentSearchResult]
    # Cursor opaco de la pagina siguiente (``after``); ``None`` si no hay mas
    # (F3-08). Sale tambien en las paginas pedidas por ``page``.
    next_cursor: Optional[str] = None
