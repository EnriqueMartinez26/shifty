from datetime import datetime
from decimal import Decimal

from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from core.validation import reject_control_chars, reject_unsafe_url
from modules.stores.media import reject_media_url, validate_image_url


class ServiceBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    description: str | None = Field(None, max_length=1000)
    duration_minutes: int = Field(..., gt=0, le=480)
    price: float = Field(..., ge=0, le=10_000_000)
    deposit_mode: str = Field(default="none", pattern=r"^(none|optional|required)$")
    deposit_type: str = Field(default="percent", pattern=r"^(percent|fixed|full)$")
    deposit_amount: float | None = Field(None, ge=0, le=10_000_000)
    color: str | None = Field(None, pattern=r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")
    # Una imagen subida (/api/stores/media/{id}, F1-28) o una URL http(s)
    # externa. Se valida en los schemas de entrada: la respuesta hereda de
    # esta base y una imagen subida no es http(s).
    image_url: str | None = Field(None, max_length=500)
    youtube_trailer_url: str | None = Field(None, max_length=500)


_CENT = Decimal("0.01")


def reject_sub_cent(value: float | None) -> float | None:
    """Importes con hasta 2 decimales, sin cambiar el tipo (B6-07).

    No se usa ``Field(multiple_of=0.01)``: con ``float`` rechaza importes
    validos por precision (p. ej. 9624539.79). ``Decimal(str(v))`` compara el
    numero tal como llego en el JSON.
    """
    if value is not None and Decimal(str(value)) % _CENT != 0:
        raise ValueError("el importe admite hasta 2 decimales")
    return value


DEPOSIT_FIELDS = ("deposit_mode", "deposit_type", "deposit_amount")


def deposit_policy_error(
    deposit_mode: str, deposit_type: str, deposit_amount: float | None
) -> str | None:
    """Valida la terna de sena como un solo dato (B6-02).

    ``percent`` es un porcentaje del precio: mas de 100 cobraba mas que el
    servicio. ``required`` u ``optional`` con ``percent``/``fixed`` sin monto
    calculaba una sena de 0: el turno se reservaba sin cobrar, o se ofrecia
    una sena opcional de 0. ``full`` no necesita monto; ``none`` no cobra.
    """
    if deposit_type == "percent" and deposit_amount is not None:
        if deposit_amount > 100:
            return "deposit_amount: un porcentaje de sena no puede superar 100"
    if deposit_mode != "none" and deposit_type != "full":
        if deposit_amount is None or deposit_amount <= 0:
            return "deposit_amount: una sena necesita un monto mayor a 0"
    return None


class ServiceCreate(ServiceBase):
    @field_validator("youtube_trailer_url")
    @classmethod
    def validate_media_url(cls, value: str | None) -> str | None:
        return reject_unsafe_url(value)

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str | None) -> str | None:
        # Al crear no hay imagen subida: la de servicio se sube despues con
        # POST /services/{id}/image. Una URL de medios (relativa o absoluta)
        # seria enlazar a mano la imagen de otro recurso.
        return reject_media_url(value)

    @model_validator(mode="after")
    def validate_deposit_policy(self) -> Self:
        error = deposit_policy_error(
            self.deposit_mode, self.deposit_type, self.deposit_amount
        )
        if error:
            raise ValueError(error)
        return self

    @field_validator("price", "deposit_amount")
    @classmethod
    def reject_sub_cent_amounts(cls, value: float | None) -> float | None:
        # En los schemas de entrada y no en ServiceBase: ServiceResponse
        # hereda de la base y una fila vieja con 3 decimales (SQLite) tiene
        # que seguir leyendose.
        return reject_sub_cent(value)

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

    @field_validator("price", "deposit_amount")
    @classmethod
    def reject_sub_cent_amounts(cls, value: float | None) -> float | None:
        return reject_sub_cent(value)

    @model_validator(mode="after")
    def reject_null_in_required_columns(self) -> Self:
        # B6-04: el PATCH aplica solo los campos enviados (exclude_unset), asi
        # que un null explicito BORRA. En las columnas NOT NULL eso no es un
        # borrado posible: 422 aca y no un IntegrityError en la base.
        for field in _NOT_NULL_FIELDS:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} no puede ser null")
        return self

    @field_validator("youtube_trailer_url")
    @classmethod
    def validate_media_url(cls, value: str | None) -> str | None:
        return reject_unsafe_url(value)

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str | None) -> str | None:
        # El front manda el formulario entero: la URL de la imagen ya subida
        # vuelve tal cual. Que sea LA de este servicio lo chequea
        # media.resolve_image_link.
        return validate_image_url(value)


class ServiceResponse(ServiceBase):
    public_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
