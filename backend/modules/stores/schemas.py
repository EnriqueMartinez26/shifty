from datetime import date, datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from core.business_types import BusinessType, DEFAULT_BUSINESS_TYPE
from core.validation import SLUG_PATTERN, reject_unsafe_url

# Techos de los enteros expuestos por la API.
#
# Las columnas son INTEGER de PostgreSQL: cualquier valor por encima de 2^31-1
# revienta al guardar y sale como 500. Ademas de evitar eso, los topes reflejan
# maximos con sentido de negocio.
MAX_HORAS_ANIO = 8760  # un anio
MAX_MINUTOS_DIA = 1440  # un dia
MAX_ELEMENTOS_PLAN = 10_000
MAX_USOS_CUPON = 1_000_000


CUSTOM_FIELD_KEY_PATTERN = r"^[a-z][a-z0-9_]{1,39}$"
CustomClientFieldType = Literal["text", "textarea", "tel", "email", "date", "select"]


class BusinessHourPeriod(BaseModel):
    open: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    close: str = Field(..., pattern=r"^\d{2}:\d{2}$")


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
    primary_color: Optional[str] = Field(
        None, pattern=r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$"
    )
    cover_url: Optional[str] = Field(None, max_length=500)
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

    @field_validator(
        "logo_url", "cover_url", "instagram_url", "facebook_url", "website_url"
    )
    @classmethod
    def validate_logo_url(cls, value: str | None) -> str | None:
        return reject_unsafe_url(value)


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


class StoreFeatureFlagsUpdate(BaseModel):
    payments: bool | None = None
    ledger: bool | None = None
    advanced_reports: bool | None = None
    new_calendar: bool | None = None
    otp_booking: bool | None = None


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
    feature_flags: StoreFeatureFlags

    class Config:
        from_attributes = True
