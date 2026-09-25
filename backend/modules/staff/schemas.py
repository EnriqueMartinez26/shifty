from typing import Literal, Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from datetime import time
from core.validation import PUBLIC_ID_PATTERN, reject_control_chars
from modules.services.schemas import ServiceResponse

PublicId = Annotated[str, Field(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)]
# Tope de servicios por profesional: lo comparten el alta y
# PATCH /staff/{id}/services (B3-14).
MAX_SERVICE_IDS = 100


class ScheduleBase(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def validate_time_order(self) -> "ScheduleBase":
        if self.start_time >= self.end_time:
            raise ValueError("start_time debe ser anterior a end_time")
        return self


class ScheduleCreate(ScheduleBase):
    pass


class ScheduleUpdate(BaseModel):
    """Edicion parcial de una franja horaria.

    Sin esto, un horario mal cargado era irreversible: solo existia el alta.
    """

    day_of_week: int | None = Field(None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None


class ScheduleResponse(ScheduleBase):
    public_id: str

    class Config:
        from_attributes = True


class StaffBase(BaseModel):
    display_name: str = Field(..., min_length=2, max_length=255)


class StaffCreate(StaffBase):
    # "person" exige nombre, apellido y email (crea un usuario de login).
    # "resource" (cancha, sala, box) solo exige display_name: sin email ni
    # usuario. kind es inmutable despues del alta.
    kind: Literal["person", "resource"] = "person"
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    email: EmailStr | None = None
    service_ids: list[PublicId] = Field(
        default_factory=list, max_length=MAX_SERVICE_IDS
    )

    @field_validator("display_name", "first_name", "last_name")
    @classmethod
    def reject_control_chars_in_names(cls, value: str | None) -> str | None:
        # Regla 19 leida como "texto que se publica" (B3-15): sale al portal
        # publico. Va en el schema de entrada, no en StaffBase, que hereda
        # StaffResponse: una fila legada con un invisible se sigue leyendo.
        return reject_control_chars(value)

    @model_validator(mode="after")
    def validate_by_kind(self) -> "StaffCreate":
        if self.kind == "person":
            if (
                not (self.first_name or "").strip()
                or not (self.last_name or "").strip()
            ):
                raise ValueError("Nombre y apellido son obligatorios para una persona")
            if not self.email:
                raise ValueError("El email es obligatorio para una persona")
        else:
            self.email = None
            self.first_name = (self.first_name or "").strip() or None
            self.last_name = (self.last_name or "").strip() or None
        return self


class StaffUpdate(BaseModel):
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    email: EmailStr | None = None
    display_name: str | None = Field(None, min_length=2, max_length=255)
    service_ids: list[PublicId] | None = Field(None, max_length=100)
    is_active: bool | None = None

    @field_validator("display_name", "first_name", "last_name")
    @classmethod
    def reject_control_chars_in_names(cls, value: str | None) -> str | None:
        return reject_control_chars(value)


class StaffResponse(StaffBase):
    public_id: str
    kind: str = "person"
    first_name: str
    last_name: str
    email: str | None = None
    is_active: bool
    service_ids: list[str] = Field(default_factory=list)
    services: list[ServiceResponse] = Field(default_factory=list)
    schedules: list[ScheduleResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True
