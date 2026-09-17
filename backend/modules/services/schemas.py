from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from core.validation import reject_control_chars, reject_unsafe_url


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
    @field_validator("name", "description")
    @classmethod
    def reject_control_chars_in_text(cls, value: str | None) -> str | None:
        # Regla 19: el nombre y la descripcion salen al catalogo publico y a
        # los mails al cliente. Va en los schemas de entrada y no en
        # ServiceBase porque ServiceResponse hereda de la base y un servicio
        # ya guardado con un invisible tiene que seguir leyendose.
        return reject_control_chars(value)


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

    @field_validator("name", "description")
    @classmethod
    def reject_control_chars_in_text(cls, value: str | None) -> str | None:
        return reject_control_chars(value)

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
