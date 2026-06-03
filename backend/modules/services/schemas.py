from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from core.validation import reject_unsafe_url


class ServiceBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    description: str | None = Field(None, max_length=1000)
    duration_minutes: int = Field(..., gt=0, le=480)
    price: float = Field(..., ge=0, le=10_000_000)
    deposit_mode: str = Field(default="none", pattern=r"^(none|optional|required)$")
    deposit_type: str = Field(default="percent", pattern=r"^(percent|fixed|full)$")
    deposit_amount: float | None = Field(None, ge=0, le=10_000_000)
    color: str | None = Field(None, pattern=r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")
    image_url: str | None = Field(None, max_length=500)
    youtube_trailer_url: str | None = Field(None, max_length=500)

    @field_validator("image_url", "youtube_trailer_url")
    @classmethod
    def validate_media_url(cls, value: str | None) -> str | None:
        return reject_unsafe_url(value)


class ServiceCreate(ServiceBase):
    pass


class ServiceUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    description: str | None = Field(None, max_length=1000)
    duration_minutes: int | None = Field(None, gt=0, le=480)
    price: float | None = Field(None, ge=0, le=10_000_000)
    deposit_mode: str | None = Field(None, pattern=r"^(none|optional|required)$")
    deposit_type: str | None = Field(None, pattern=r"^(percent|fixed|full)$")
    deposit_amount: float | None = Field(None, ge=0, le=10_000_000)
    color: str | None = Field(None, pattern=r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")
    image_url: str | None = Field(None, max_length=500)
    youtube_trailer_url: str | None = Field(None, max_length=500)
    is_active: bool | None = None

    @field_validator("image_url", "youtube_trailer_url")
    @classmethod
    def validate_media_url(cls, value: str | None) -> str | None:
        return reject_unsafe_url(value)


class ServiceResponse(ServiceBase):
    public_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
