from datetime import datetime
from decimal import Decimal

from typing import Annotated, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from core.validation import (
    PUBLIC_ID_PATTERN,
    reject_control_chars,
    reject_unsafe_url,
)
from modules.services.model import (
    ADDON_MAX_QUANTITY,
    ADDON_MAX_UNIT_PRICE,
    ADDONS_PER_SERVICE,
    PRIOR_DESIGN_MESSAGE_MAX,
)
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
    # Diseno previo (2026-10-21): solo un aviso al cliente con su mensaje; el
    # cobro y la sena no cambian. El mensaje se valida en los schemas de
    # entrada (``clean_prior_design_message``), igual que el nombre.
    requires_prior_design: bool = False
    prior_design_message: str | None = Field(None, max_length=PRIOR_DESIGN_MESSAGE_MAX)


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


class ServiceAddonInput(BaseModel):
    """Un adicional del servicio tal como lo carga el panel.

    Suma precio, nunca tiempo (decision de Mateo, 2026-10-14). La lista es
    el conjunto completo y la posicion es el indice. ``id`` (opcional) es el
    de un adicional que ya existe: si es de ESTE servicio y el precio no
    cambio, conserva el id (``ServiceRepository.replace_addons``); si no, nace
    uno nuevo.
    """

    id: str | None = Field(None, min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
    name: str = Field(..., min_length=1, max_length=100)
    unit_price: float = Field(..., ge=0, le=ADDON_MAX_UNIT_PRICE)
    max_quantity: int = Field(1, ge=1, le=ADDON_MAX_QUANTITY)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        # Regla 19: sale al catalogo publico, a la agenda y a los mails.
        cleaned = (reject_control_chars(value) or "").strip()
        if not cleaned:
            raise ValueError("el nombre del adicional no puede quedar vacio")
        return cleaned

    @field_validator("unit_price")
    @classmethod
    def reject_sub_cent_price(cls, value: float) -> float:
        reject_sub_cent(value)
        return value


def clean_prior_design_message(value: str | None) -> str | None:
    """Regla 19 (sale al portal publico), recortado; vacio queda en null."""
    cleaned = (reject_control_chars(value) or "").strip()
    return cleaned or None


AddonList = Annotated[list[ServiceAddonInput], Field(max_length=ADDONS_PER_SERVICE)]


def reject_duplicated_addon_names(
    addons: list[ServiceAddonInput] | None,
) -> list[ServiceAddonInput] | None:
    """Dos adicionales con el mismo nombre (sin distinguir mayusculas) son
    indistinguibles para el cliente y en el snapshot del turno; dos con el
    mismo ``id`` serian el mismo adicional dos veces."""
    if addons is None:
        return None
    names = [addon.name.casefold() for addon in addons]
    if len(names) != len(set(names)):
        raise ValueError("addons: hay dos adicionales con el mismo nombre")
    ids = [addon.id for addon in addons if addon.id is not None]
    if len(ids) != len(set(ids)):
        raise ValueError("addons: hay dos adicionales con el mismo id")
    return addons


class ServiceAddonResponse(BaseModel):
    id: str
    name: str
    unit_price: float
    max_quantity: int
    position: int

    class Config:
        from_attributes = True


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
    # Si viene, es el conjunto completo de adicionales del servicio.
    addons: AddonList | None = None

    @field_validator("addons")
    @classmethod
    def unique_addon_names(
        cls, value: list[ServiceAddonInput] | None
    ) -> list[ServiceAddonInput] | None:
        return reject_duplicated_addon_names(value)

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

    @field_validator("prior_design_message")
    @classmethod
    def validate_prior_design_message(cls, value: str | None) -> str | None:
        return clean_prior_design_message(value)


# Columnas NOT NULL de services que el PATCH puede tocar.
_NOT_NULL_FIELDS = (
    "name",
    "duration_minutes",
    "price",
    "deposit_mode",
    "deposit_type",
    "is_active",
    "requires_prior_design",
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
    requires_prior_design: bool | None = None
    # Un null explicito (o un texto vacio) borra el mensaje.
    prior_design_message: str | None = Field(None, max_length=PRIOR_DESIGN_MESSAGE_MAX)
    # Si viene, REEMPLAZA el conjunto de adicionales (una lista vacia los
    # quita todos). Un null explicito no cambia nada.
    addons: AddonList | None = None

    @field_validator("addons")
    @classmethod
    def unique_addon_names(
        cls, value: list[ServiceAddonInput] | None
    ) -> list[ServiceAddonInput] | None:
        return reject_duplicated_addon_names(value)

    @field_validator("name", "description")
    @classmethod
    def reject_control_chars_in_text(cls, value: str | None) -> str | None:
        return reject_control_chars(value)

    @field_validator("prior_design_message")
    @classmethod
    def validate_prior_design_message(cls, value: str | None) -> str | None:
        return clean_prior_design_message(value)

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


class ServiceCatalogResponse(ServiceResponse):
    """El servicio con sus adicionales, para ``/services`` (el catalogo).

    Aparte de ``ServiceResponse`` para que el listado de personal, que embebe
    sus servicios sin leer adicionales, no los muestre vacios.
    """

    # Ordenados por ``position``. Los arma el mapper (una consulta con
    # ``in_()``): el modelo no tiene relacion para no cargarlos sin querer.
    addons: list[ServiceAddonResponse] = Field(default_factory=list)
