from datetime import datetime

from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

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


# Columnas NOT NULL de services que el PATCH puede tocar.
_NOT_NULL_FIELDS = (
    "name",
    "duration_minutes",
    "price",
    "deposit_mode",
    "deposit_type",
    "is_active",
)


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

    @model_validator(mode="after")
    def reject_null_in_required_columns(self) -> Self:
        # B6-04: el PATCH aplica solo los campos enviados (exclude_unset), asi
        # que un null explicito BORRA. En las columnas NOT NULL eso no es un
        # borrado posible: 422 aca y no un IntegrityError en la base.
        for field in _NOT_NULL_FIELDS:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} no puede ser null")
        return self

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
