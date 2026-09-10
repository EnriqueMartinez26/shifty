from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class AppointmentBlockBase(BaseModel):
    staff_id: str = Field(..., min_length=1, max_length=64)
    starts_at: datetime
    ends_at: datetime
    reason: str = Field("No atender", max_length=255)

    @model_validator(mode="after")
    def validate_range(self) -> "AppointmentBlockBase":
        if self.starts_at >= self.ends_at:
            raise ValueError("El inicio debe ser anterior al fin")
        return self


class StoreWideBlockCreate(BaseModel):
    """Cierre de toda la tienda: un feriado, una mudanza, un dia de limpieza.

    Sin esto habia que bloquear a cada profesional uno por uno, y con cinco
    empleados cerrar un dia eran cinco operaciones.
    """

    starts_at: datetime
    ends_at: datetime
    reason: str = Field("Cerrado", max_length=255)
    # Si hay turnos reservados adentro, sin este flag el alta responde 409 con
    # la cantidad; con el flag (solo administradores) se cancelan los que se
    # pueden y se avisa al cliente por mail.
    cancel_affected: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> "StoreWideBlockCreate":
        if self.starts_at >= self.ends_at:
            raise ValueError("El inicio debe ser anterior al fin")
        return self


class StoreWideBlockResponse(BaseModel):
    """Resultado del cierre: a cuantos profesionales alcanzo."""

    blocked_staff: int
    starts_at: datetime
    ends_at: datetime
    reason: str


class AppointmentBlockCreate(AppointmentBlockBase):
    cancel_affected: bool = False


class RecurringAppointmentBlockCreate(AppointmentBlockBase):
    recurrence: str = Field(default="none", pattern=r"^(none|daily|weekly)$")
    recurrence_until: datetime | None = None
    max_occurrences: int = Field(default=30, ge=1, le=120)
    cancel_affected: bool = False

    @model_validator(mode="after")
    def validate_recurrence(self) -> "RecurringAppointmentBlockCreate":
        if self.recurrence != "none" and self.recurrence_until is None:
            raise ValueError(
                "recurrence_until es obligatorio cuando recurrence no es none"
            )
        if self.recurrence_until and self.recurrence_until <= self.starts_at:
            raise ValueError("recurrence_until debe ser posterior al inicio")
        return self


class AppointmentBlockUpdate(BaseModel):
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str | None = Field(None, max_length=255)
    is_active: bool | None = None


class AppointmentBlockResponse(BaseModel):
    public_id: str
    staff_id: str
    starts_at: datetime
    ends_at: datetime
    reason: str
    is_active: bool

    class Config:
        from_attributes = True


class AppointmentBlockBatchResponse(BaseModel):
    created: int
    blocks: list[AppointmentBlockResponse]


class BlockTemplateResponse(BaseModel):
    key: str
    label: str
    reason: str


class BlockPreviewRequest(BaseModel):
    """Que turnos caerian dentro de un bloqueo (sin escribir nada).

    ``staff_id`` en null significa toda la tienda (cierre).
    """

    staff_id: str | None = Field(None, min_length=1, max_length=64)
    starts_at: datetime
    ends_at: datetime
    recurrence: str = Field(default="none", pattern=r"^(none|daily|weekly)$")
    recurrence_until: datetime | None = None
    max_occurrences: int = Field(default=30, ge=1, le=120)

    @model_validator(mode="after")
    def validate_ranges(self) -> "BlockPreviewRequest":
        if self.starts_at >= self.ends_at:
            raise ValueError("El inicio debe ser anterior al fin")
        if self.recurrence != "none" and self.recurrence_until is None:
            raise ValueError(
                "recurrence_until es obligatorio cuando recurrence no es none"
            )
        if self.recurrence_until and self.recurrence_until <= self.starts_at:
            raise ValueError("recurrence_until debe ser posterior al inicio")
        return self


class AffectedAppointmentResponse(BaseModel):
    public_id: str
    client_name: str
    client_phone: str | None = None
    service_name: str
    staff_name: str
    starts_at: datetime
    ends_at: datetime
    status: str
    # None = se cancela con cancel_affected; "pending_payment" = esperando la
    # sena en Mercado Pago (liberar a mano); "has_deposit" = sena acreditada
    # (decision del dueno).
    blocker: str | None = None
    cancellable: bool


class BlockPreviewResponse(BaseModel):
    ranges: int
    affected: list[AffectedAppointmentResponse]
