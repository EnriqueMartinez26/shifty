from pydantic import BaseModel, Field, field_validator
from datetime import datetime

from core.validation import reject_unsafe_url

class ServiceBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    description: str | None = Field(None, max_length=1000)
    duration_minutes: int = Field(..., gt=0, le=480) # Máximo 8 horas
    price: float = Field(..., ge=0, le=10_000_000)
    color: str | None = Field(None, pattern=r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")
    youtube_trailer_url: str | None = Field(None, max_length=500)

    @field_validator("youtube_trailer_url")
    @classmethod
    def validate_youtube_url(cls, value: str | None) -> str | None:
        return reject_unsafe_url(value)

class ServiceCreate(ServiceBase):
    pass

class ServiceUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    description: str | None = Field(None, max_length=1000)
    duration_minutes: int | None = Field(None, gt=0, le=480)
    price: float | None = Field(None, ge=0, le=10_000_000)
    color: str | None = Field(None, pattern=r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")
    youtube_trailer_url: str | None = Field(None, max_length=500)
    is_active: bool | None = None

    @field_validator("youtube_trailer_url")
    @classmethod
    def validate_youtube_url(cls, value: str | None) -> str | None:
        return reject_unsafe_url(value)

class ServiceResponse(ServiceBase):
    public_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
