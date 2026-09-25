from datetime import datetime, timezone
from typing import Optional
import re

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from core.utils import now_utc, within_booking_horizon
from core.validation import (
    PUBLIC_ID_PATTERN,
    normalize_client_phone,
    reject_control_chars,
    reject_payload_control_chars,
)
from modules.stores.schemas import StoreCustomField


class PublicStoreRefResponse(BaseModel):
    """Referencia minima de la tienda para "Mis turnos" (FF-16).

    Sale tambien con la suscripcion suspendida: el cliente tiene que poder
    cancelar o reprogramar lo que ya reservo. De la suscripcion solo expone
    si la tienda toma reservas nuevas.
    """

    store_public_id: str
    name: str
    accepts_new_bookings: bool


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
    kind: str = "person"
    first_name: str
    last_name: str
    email: Optional[str] = None
    display_name: str
    service_ids: list[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


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
    # Obligatoria en el servidor (PV-09): antes solo la exigia el checkbox del
    # front y un POST directo reservaba sin consentimiento registrado.
    accepts_terms: bool = False

    @field_validator("client_phone")
    @classmethod
    def phone_must_be_numeric(cls, value: str) -> str:
        return normalize_client_phone(value)

    @field_validator("starts_at")
    @classmethod
    def must_be_future(cls, value: datetime) -> datetime:
        # Sin offset se asume UTC, una sola vez y aca (regla 24, B1-11): antes
        # se comparaba contra la hora local del proceso.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        if value <= now_utc():
            raise ValueError("No se puede agendar un turno en el pasado")
        # El horizonte de la disponibilidad publica: nadie podia elegir un
        # slot mas alla, y 9999-12-31 desbordaba ``starts_at + duracion`` (500).
        if not within_booking_horizon(value):
            raise ValueError("La fecha esta fuera del rango de reservas")
        return value

    @model_validator(mode="after")
    def require_terms(self) -> "PublicBookingCreate":
        if self.accepts_terms is not True:
            raise ValueError(
                "Para reservar hay que aceptar los terminos y la politica de sena"
            )
        return self

    @model_validator(mode="after")
    def reject_control_chars_in_text(self) -> "PublicBookingCreate":
        # Campos de texto libre controlados por un atacante ANONIMO: se rechazan
        # control chars, bidi-overrides y zero-width antes de persistirlos y
        # mostrarlos (panel/portal) o exportarlos.
        self.client_name = reject_payload_control_chars(self.client_name)
        self.notes = reject_payload_control_chars(self.notes)
        self.custom_fields = reject_payload_control_chars(self.custom_fields)
        return self


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


class PublicDepositPreviewResponse(BaseModel):
    amount: float
    base_amount: float
    extra_percent: int
    reasons: list[str] = Field(default_factory=list)
    price: float
    payments_enabled: bool
    online_payment_mandatory: bool


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

    @field_validator("reason")
    @classmethod
    def reject_control_chars_in_reason(cls, value: str | None) -> str | None:
        # Texto libre de un anonimo que termina en el aviso al duenio
        # (regla 19, B1-23): sin NUL, bidi ni zero-width.
        return reject_control_chars(value)


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
        # Mismo criterio que PublicBookingCreate.starts_at (B1-11).
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        if value <= now_utc():
            raise ValueError("La nueva fecha debe ser en el futuro")
        return value


class OtpRequestPayload(BaseModel):
    store_public_id: str = Field(
        ..., min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN
    )
    phone: str = Field(..., min_length=6, max_length=30)
    # email es el unico canal con despacho real (SMTP existente, costo cero).
    # whatsapp/sms solo funcionan en desarrollo (OTP_PROVIDER=console, con el
    # codigo expuesto en la respuesta); en produccion se rechazan.
    channel: str = Field(default="email", pattern=r"^(email|whatsapp|sms)$")
    email: Optional[EmailStr] = Field(default=None, max_length=255)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        return re.sub(r"[\s\-\(\)]", "", value)

    @model_validator(mode="after")
    def email_required_for_email_channel(self) -> "OtpRequestPayload":
        if self.channel == "email" and not self.email:
            raise ValueError(
                "Para recibir el codigo por email hay que indicar un email"
            )
        return self


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
