from datetime import datetime
from typing import Optional
import re

from pydantic import BaseModel, EmailStr, Field, field_validator

from core.validation import PUBLIC_ID_PATTERN
from modules.stores.schemas import StoreCustomField


class PublicStoreResponse(BaseModel):
    public_id: str
    name: str
    slug: str
    business_type: str = "generic"
    logo_url: Optional[str] = None
    primary_color: str
    cancellation_hours: int
    description: Optional[str] = None
    cover_url: Optional[str] = None
    whatsapp_number: Optional[str] = None
    website_url: Optional[str] = None
    # La politica de seña y la posibilidad de coordinar por fuera se muestran al
    # cliente antes de reservar, para que sepa a que se compromete.
    allow_manual_coordination: bool = True
    deposit_policy: Optional[str] = None
    custom_client_fields: list[StoreCustomField] = Field(default_factory=list)
    feature_flags: dict[str, bool] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class PublicServiceResponse(BaseModel):
    public_id: str
    name: str
    description: Optional[str] = None
    duration_minutes: int
    price: float
    deposit_mode: str = "none"
    deposit_type: str = "percent"
    deposit_amount: float | None = None
    color: Optional[str] = None
    image_url: Optional[str] = None

    class Config:
        from_attributes = True


class PublicStaffResponse(BaseModel):
    public_id: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    display_name: str
    service_ids: list[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class AvailabilitySlot(BaseModel):
    staff_id: str
    staff_name: str
    starts_at: str
    ends_at: str
    status: str


class PublicBookingCreate(BaseModel):
    store_public_id: Optional[str] = Field(
        None, min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN
    )
    service_id: str = Field(..., min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
    staff_id: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN
    )
    starts_at: datetime
    notes: Optional[str] = Field(None, max_length=500)
    idempotency_key: Optional[str] = Field(default=None, min_length=10, max_length=128)
    client_name: str = Field(..., min_length=1, max_length=100)
    client_phone: str = Field(..., min_length=6, max_length=30)
    client_email: Optional[EmailStr] = Field(default=None, max_length=255)
    custom_fields: dict[str, str] = Field(default_factory=dict, max_length=12)
    promotion_code: str | None = Field(
        default=None, min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_-]+$"
    )
    payment_method: str = Field(
        default="manual", pattern=r"^(auto|manual|mercadopago)$"
    )
    # Aceptacion de los terminos de Shifty y de la politica de seña de la tienda.
    accepts_terms: bool = False

    @field_validator("client_phone")
    @classmethod
    def phone_must_be_numeric(cls, value: str) -> str:
        cleaned = re.sub(r"[\s\-\(\)\+]", "", value)
        if not cleaned.isdigit():
            raise ValueError(
                "El telefono solo puede contener digitos, espacios o los caracteres: + - ( )"
            )
        if len(cleaned) < 6:
            raise ValueError("El telefono debe tener al menos 6 digitos")
        return cleaned

    @field_validator("starts_at")
    @classmethod
    def must_be_future(cls, value: datetime) -> datetime:
        now = datetime.now(value.tzinfo) if value.tzinfo else datetime.now()
        if value <= now:
            raise ValueError("No se puede agendar un turno en el pasado")
        return value


class PublicBookingResponse(BaseModel):
    public_id: str
    service_id: str
    service_name: str
    staff_id: str
    staff_name: str
    starts_at: datetime
    ends_at: datetime
    status: str
    client_name: str
    client_phone: str
    notes: Optional[str] = None
    custom_fields: dict[str, str] = Field(default_factory=dict)
    payment_required: bool = False
    payment_status: str | None = None
    payment_link: str | None = None
    payment_public_id: str | None = None
    payment_amount: float | None = None
    promotion_code: str | None = None
    service_price: float | None = None
    discount_amount: float | None = None
    final_price: float | None = None

    class Config:
        from_attributes = True


class PublicPaymentStatusResponse(BaseModel):
    payment_public_id: str
    appointment_public_id: str
    payment_status: str
    appointment_status: str
    amount: float
    currency: str
    starts_at: datetime


class PublicPromotionPreviewResponse(BaseModel):
    code: str
    title: str
    promotion_type: str
    base_amount: float
    discount_amount: float
    final_amount: float


class ClientAppointmentItem(BaseModel):
    public_id: str
    service_name: str
    staff_name: str
    starts_at: datetime
    ends_at: datetime
    status: str
    notes: Optional[str] = None
    custom_fields: dict[str, str] = Field(default_factory=dict)
    can_cancel: bool
    can_reschedule: bool


class ClientAppointmentsResponse(BaseModel):
    client_name: str
    client_phone: str
    appointments: list[ClientAppointmentItem]


class ClientCancelRequest(BaseModel):
    phone: str = Field(..., min_length=6, max_length=30)
    reason: Optional[str] = Field(None, max_length=500)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        return re.sub(r"[\s\-\(\)\+]", "", value)


class ClientRescheduleRequest(BaseModel):
    phone: str = Field(..., min_length=6, max_length=30)
    new_starts_at: datetime
    idempotency_key: str = Field(..., min_length=10, max_length=128)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        return re.sub(r"[\s\-\(\)\+]", "", value)

    @field_validator("new_starts_at")
    @classmethod
    def validate_new_starts_at(cls, value: datetime) -> datetime:
        now = datetime.now(value.tzinfo) if value.tzinfo else datetime.now()
        if value <= now:
            raise ValueError("La nueva fecha debe ser en el futuro")
        return value


class OtpRequestPayload(BaseModel):
    store_public_id: str = Field(
        ..., min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN
    )
    phone: str = Field(..., min_length=6, max_length=30)
    channel: str = Field(default="whatsapp", pattern=r"^(whatsapp|sms)$")

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        return re.sub(r"[\s\-\(\)]", "", value)


class OtpVerifyPayload(BaseModel):
    store_public_id: str = Field(
        ..., min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN
    )
    phone: str = Field(..., min_length=6, max_length=30)
    code: str = Field(..., min_length=4, max_length=8)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        return re.sub(r"[\s\-\(\)]", "", value)
