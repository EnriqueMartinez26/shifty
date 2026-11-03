from datetime import date, datetime, time
from typing import Dict, List, Literal, Optional

from email_validator import EmailNotValidError, validate_email
from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from core.business_types import BusinessType, DEFAULT_BUSINESS_TYPE
from core.validation import (
    SLUG_PATTERN,
    reject_control_chars,
    reject_payload_control_chars,
    reject_unsafe_url,
)
from modules.auth.service import normalize_email
from modules.stores.media import validate_image_url
from modules.stores.model import CoverPosition

# Techos de los enteros expuestos por la API.
#
# Las columnas son INTEGER de PostgreSQL: cualquier valor por encima de 2^31-1
# revienta al guardar y sale como 500. Ademas de evitar eso, los topes reflejan
# maximos con sentido de negocio.
MAX_HORAS_ANIO = 8760  # un anio
MAX_MINUTOS_DIA = 1440  # un dia
MAX_ELEMENTOS_PLAN = 10_000
MAX_USOS_CUPON = 1_000_000
# Largo maximo de una direccion (RFC 5321) y de la columna stores.contact_email.
CONTACT_EMAIL_MAX_LENGTH = 254


CUSTOM_FIELD_KEY_PATTERN = r"^[a-z][a-z0-9_]{1,39}$"
# El color del negocio sale al tema del portal publico como valor CSS: es
# texto publicado (regla 19). Vive aca, junto al schema que es dueno del
# campo, y lo importa el de superadmin para que no haya dos versiones del
# mismo contrato (AUD2-B3-13).
HEX_COLOR_PATTERN = r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$"
CustomClientFieldType = Literal["text", "textarea", "tel", "email", "date", "select"]


class BusinessHourPeriod(BaseModel):
    # La hora del local es una hora, no una cadena: "99:99" cumplia el patron
    # ^\d{2}:\d{2}$ y reventaba en time.fromisoformat del router (500). Con
    # `time` la validacion la hace Pydantic (422), igual que ScheduleBase en
    # staff. El contrato de salida no cambia: se serializa como "HH:MM".
    open: time
    close: time

    @field_serializer("open", "close", when_used="json")
    def _hh_mm(self, value: time) -> str:
        return value.strftime("%H:%M")

    @model_validator(mode="after")
    def validate_time_order(self) -> "BusinessHourPeriod":
        if self.open >= self.close:
            raise ValueError("open debe ser anterior a close")
        return self


class StoreCustomFieldOption(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    value: str = Field(..., min_length=1, max_length=80)


class StoreCustomField(BaseModel):
    key: str = Field(..., min_length=2, max_length=40, pattern=CUSTOM_FIELD_KEY_PATTERN)
    label: str = Field(..., min_length=1, max_length=80)
    type: CustomClientFieldType = "text"
    required: bool = False
    placeholder: Optional[str] = Field(None, max_length=120)
    help_text: Optional[str] = Field(None, max_length=200)
    options: List[StoreCustomFieldOption] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_options(self) -> "StoreCustomField":
        if self.type == "select" and not self.options:
            raise ValueError("Los campos de tipo select requieren al menos una opcion")
        return self


class StoreUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    slug: Optional[str] = Field(None, max_length=100, pattern=SLUG_PATTERN)
    business_type: Optional[BusinessType] = None
    logo_url: Optional[str] = Field(None, max_length=500)
    primary_color: Optional[str] = Field(None, pattern=HEX_COLOR_PATTERN)
    cover_url: Optional[str] = Field(None, max_length=500)
    # Punto focal de la portada; null lo vuelve a "sin elegir".
    cover_position: Optional[CoverPosition] = None
    description: Optional[str] = Field(None, max_length=2000)
    whatsapp_number: Optional[str] = Field(None, max_length=50)
    instagram_url: Optional[str] = Field(None, max_length=500)
    facebook_url: Optional[str] = Field(None, max_length=500)
    website_url: Optional[str] = Field(None, max_length=500)
    custom_client_fields: Optional[List[StoreCustomField]] = Field(None, max_length=8)

    cancellation_hours: Optional[int] = Field(None, ge=0, le=MAX_HORAS_ANIO)
    # Antelacion minima para reservar por el portal (hasta una semana).
    min_booking_notice_hours: Optional[int] = Field(None, ge=0, le=168)
    buffer_minutes: Optional[int] = Field(None, ge=0, le=MAX_MINUTOS_DIA)
    allow_manual_coordination: Optional[bool] = None
    deposit_policy: Optional[str] = Field(None, max_length=2000)
    # Recargos de sena (puntos porcentuales del precio); 0 apaga la regla.
    deposit_far_notice_days: Optional[int] = Field(None, ge=0, le=365)
    deposit_far_notice_extra_percent: Optional[int] = Field(None, ge=0, le=100)
    deposit_new_client_extra_percent: Optional[int] = Field(None, ge=0, le=100)
    deposit_absent_client_extra_percent: Optional[int] = Field(None, ge=0, le=100)

    business_hours: Optional[Dict[str, List[BusinessHourPeriod]]] = Field(
        None, max_length=7
    )

    send_email_confirmation: Optional[bool] = None
    send_email_reminders: Optional[bool] = None
    # Reply-To de los mails al cliente (#283). Vacio o null lo borra.
    contact_email: Optional[EmailStr] = Field(None, max_length=CONTACT_EMAIL_MAX_LENGTH)

    @field_validator("contact_email", mode="before")
    @classmethod
    def normalize_contact_email(cls, value: object) -> object:
        # Antes de EmailStr: la regla 19 mira el texto crudo, un vacio es
        # "sin contacto" y el guardado va en minusculas, como los emails de
        # las cuentas (regla 16).
        if not isinstance(value, str):
            return value
        limpio = reject_control_chars(value.strip())
        return normalize_email(limpio) if limpio else None

    @field_validator("contact_email", mode="after")
    @classmethod
    def contact_email_in_ascii(cls, value: str | None) -> str | None:
        # Se guarda la forma ASCII (verificacion, 2026-11-03): EmailStr
        # devuelve el dominio en Unicode y el Reply-To salia con un
        # encoded-word dentro de la direccion. Un dominio IDN queda en
        # punycode; un local con tildes o ñ no tiene forma ASCII y es 422.
        if value is None:
            return None
        try:
            ascii_email = validate_email(
                value, check_deliverability=False, allow_smtputf8=False
            ).ascii_email
        except EmailNotValidError:
            raise ValueError(
                "El mail de contacto no puede llevar tildes ni ñ"
            ) from None
        if ascii_email is None or len(ascii_email) > CONTACT_EMAIL_MAX_LENGTH:
            raise ValueError("El mail de contacto no es valido")
        return normalize_email(ascii_email)

    @field_validator("instagram_url", "facebook_url", "website_url")
    @classmethod
    def validate_logo_url(cls, value: str | None) -> str | None:
        return reject_unsafe_url(value)

    @field_validator("logo_url", "cover_url")
    @classmethod
    def validate_image_url(cls, value: str | None) -> str | None:
        # La imagen subida (/api/stores/media/{id}) o una URL http(s). Que la
        # subida sea la de la tienda lo chequea el router (F1-30).
        return validate_image_url(value)

    @field_validator("name", "description", "whatsapp_number", "deposit_policy")
    @classmethod
    def reject_control_chars_in_text(cls, value: str | None) -> str | None:
        # Regla 19 leida como "texto que se publica" (B3-15): sale al portal
        # publico. Va en el schema de entrada, no en una base que herede la
        # respuesta: una fila legada con un invisible se sigue leyendo.
        return reject_control_chars(value)

    @field_validator("custom_client_fields")
    @classmethod
    def reject_control_chars_in_custom_fields(
        cls, value: Optional[List[StoreCustomField]]
    ) -> Optional[List[StoreCustomField]]:
        # Etiquetas, ayudas y opciones del formulario de reserva: tambien se
        # publican. StoreCustomField no se toca porque la respuesta lo reusa.
        if value is not None:
            reject_payload_control_chars([campo.model_dump() for campo in value])
        return value

    @field_validator("business_hours")
    @classmethod
    def reject_extra_periods(
        cls, value: Optional[Dict[str, List[BusinessHourPeriod]]]
    ) -> Optional[Dict[str, List[BusinessHourPeriod]]]:
        """Un dia, un periodo: lo que no se persiste se rechaza (AUD2-B3-07).

        El router guarda ``periods[0]`` y descartaba el resto en silencio, asi
        que un local con corte de mediodia recibia 200 y quedaba abierto medio
        dia. Soportar horario partido es decision de producto y esta pendiente;
        hasta entonces un 200 que guarda menos de lo enviado es una mentira de
        contrato, y esto la convierte en un 422 con mensaje neutro.
        """
        if value is None:
            return value
        if any(len(periodos) > 1 for periodos in value.values()):
            raise ValueError("Por ahora cada dia admite un solo periodo de apertura")
        return value


class StoreMediaUploadResponse(BaseModel):
    url: str
    media_id: str
    kind: str


class StoreFeatureFlags(BaseModel):
    payments: bool = False
    ledger: bool = False
    advanced_reports: bool = False
    new_calendar: bool = False
    otp_booking: bool = False
    multi_service_booking: bool = False


class StoreFeatureFlagsUpdate(BaseModel):
    payments: bool | None = None
    ledger: bool | None = None
    advanced_reports: bool | None = None
    new_calendar: bool | None = None
    otp_booking: bool | None = None
    multi_service_booking: bool | None = None


class StoreFeatureFlagsResponse(BaseModel):
    flags: StoreFeatureFlags


class StoreSubscriptionStatusResponse(BaseModel):
    """Lo que el dueno ve de su plan: sin importes internos ni ids de billing."""

    status: str
    plan_name: Optional[str] = None
    current_period_end: Optional[datetime] = None
    days_left: Optional[int] = None
    grace_until: Optional[date] = None
    warn: bool = False
    blocks_writes: bool = False


class StoreResponse(BaseModel):
    public_id: str
    name: str
    slug: str
    business_type: BusinessType = DEFAULT_BUSINESS_TYPE
    logo_url: Optional[str]
    primary_color: str
    cover_url: Optional[str] = None
    cover_position: Optional[CoverPosition] = None
    description: Optional[str] = None
    whatsapp_number: Optional[str] = None
    instagram_url: Optional[str] = None
    facebook_url: Optional[str] = None
    website_url: Optional[str] = None
    custom_client_fields: List[StoreCustomField] = Field(default_factory=list)
    cancellation_hours: int
    min_booking_notice_hours: int = 2
    buffer_minutes: int
    allow_manual_coordination: bool = True
    deposit_policy: Optional[str] = None
    deposit_far_notice_days: int = 0
    deposit_far_notice_extra_percent: int = 0
    deposit_new_client_extra_percent: int = 0
    deposit_absent_client_extra_percent: int = 0
    business_hours: Dict[str, List[BusinessHourPeriod]]
    send_email_confirmation: bool
    send_email_reminders: bool
    contact_email: Optional[str] = None
    feature_flags: StoreFeatureFlags

    class Config:
        from_attributes = True
