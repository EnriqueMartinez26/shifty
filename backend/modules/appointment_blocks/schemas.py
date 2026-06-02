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


class AppointmentBlockCreate(AppointmentBlockBase):
    pass


class RecurringAppointmentBlockCreate(AppointmentBlockBase):
    recurrence: str = Field(default="none", pattern=r"^(none|daily|weekly)$")
    recurrence_until: datetime | None = None
    max_occurrences: int = Field(default=30, ge=1, le=120)

    @model_validator(mode="after")
    def validate_recurrence(self) -> "RecurringAppointmentBlockCreate":
        if self.recurrence != "none" and self.recurrence_until is None:
            raise ValueError("recurrence_until es obligatorio cuando recurrence no es none")
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
