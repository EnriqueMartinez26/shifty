from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, model_validator
from datetime import time
from core.validation import PUBLIC_ID_PATTERN
from modules.services.schemas import ServiceResponse

PublicId = Annotated[str, Field(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)]


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


class ScheduleResponse(ScheduleBase):
    public_id: str

    class Config:
        from_attributes = True


class StaffBase(BaseModel):
    display_name: str = Field(..., min_length=2, max_length=255)


class StaffCreate(StaffBase):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    service_ids: list[PublicId] = Field(default_factory=list, max_length=100)


class StaffUpdate(BaseModel):
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    email: EmailStr | None = None
    display_name: str | None = Field(None, min_length=2, max_length=255)
    service_ids: list[PublicId] | None = Field(None, max_length=100)
    is_active: bool | None = None


class StaffResponse(StaffBase):
    public_id: str
    first_name: str
    last_name: str
    email: str
    is_active: bool
    service_ids: list[str] = Field(default_factory=list)
    services: list[ServiceResponse] = Field(default_factory=list)
    schedules: list[ScheduleResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True
