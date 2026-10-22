from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional
import re

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from core.utils import MAX_BOOKING_AHEAD, now_utc, within_max_ahead
from modules.legal.versions import LegalVersion
from core.validation import (
    PUBLIC_ID_PATTERN,
    normalize_client_phone,
    reject_control_chars,
    reject_payload_control_chars,
)
from modules.services.model import ADDON_MAX_QUANTITY, ADDONS_PER_SERVICE
from modules.services.selection import EXTRA_SERVICES_INPUT_MAX
from modules.services.schemas import ServiceAddonResponse
from modules.stores.model import CoverPosition
from modules.stores.schemas import StoreCustomField


# Id publico de un servicio extra de la reserva (2026-10-16).
ExtraServiceId = Annotated[
    str, Field(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


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
    # Aditivo (S10.1, 2026-10-22): punto focal de la portada; null sin elegir.
    cover_position: Optional[CoverPosition] = None
    whatsapp_number: Optional[str] = None
    website_url: Optional[str] = None
    # La politica de seña y la posibilidad de coordinar por fuera se muestran al
    # cliente antes de reservar, para que sepa a que se compromete.
    allow_manual_coordination: bool = True
    deposit_policy: Optional[str] = None
    custom_client_fields: list[StoreCustomField] = Field(default_factory=list)
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    # Aditivo (decision de Mateo, 2026-10-20): si no es null, un servicio con
    # ``deposit_mode = required`` se reserva hasta hoy + N dias (hora
    # argentina); mas lejos es 422 ``FAR_BOOKING_UNAVAILABLE``. Null: la
    # tienda cobra por Mercado Pago y esta regla no corta nada.
    deposit_far_limit_days: int | None = None

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
    # Diseno previo (2026-10-21): el portal muestra el mensaje para que el
    # cliente mande su diseno; el cobro y la sena no cambian. Aditivo.
    requires_prior_design: bool = False
    prior_design_message: Optional[str] = None
    # Adicionales del servicio, en orden de ``position``: suman precio, nunca
    # tiempo (decision de Mateo, 2026-10-14). Aditivo.
    addons: list[ServiceAddonResponse] = Field(default_factory=list)

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


# Email de la reserva publica (propuesta por Mateo, 2026-10-16, pendiente de
# OK del dueño): opcional, salvo en una tienda con ``otp_booking``, donde el
# codigo sale SOLO por email y sin email no hay forma de verificar. Ese 422 lo
# levanta ``PublicBookingService._resolve_request`` (``CLIENT_EMAIL_REQUIRED``)
# antes de escribir nada. Sin email la ficha nace con el tecnico
# ``{tel}@store{id}.noreply``: no recibe avisos ni entra a "Mis turnos". El
# alta del panel nunca lo pidio. La lista de espera publica sigue exigiendolo.
PUBLIC_BOOKING_EMAIL_REQUIRED = (
    "Para reservar hace falta un email: ahí te enviamos la confirmación "
    "y el acceso a tus turnos."
)


def blank_client_email_to_none(data: Any) -> Any:
    """Un email en blanco es "sin email": el wizard manda ``""`` cuando el
    campo opcional queda vacio y ``EmailStr`` lo rechazaria como invalido."""
    if isinstance(data, dict):
        email = data.get("client_email")
        if isinstance(email, str) and not email.strip():
            return {**data, "client_email": None}
    return data


def require_client_email(data: Any, message: str) -> Any:
    """Antes de validar el campo: sin email (ausente, nulo o en blanco) el 422
    lleva un mensaje claro y neutro en vez del "Field required" de Pydantic
    (regla 20). Un email presente pero invalido sigue el camino de ``EmailStr``.
    """
    if isinstance(data, dict):
        email = data.get("client_email")
        if email is None or (isinstance(email, str) and not email.strip()):
            raise PydanticCustomError("client_email_required", message)
    return data


class PublicAddonChoice(BaseModel):
    """Un adicional elegido en la reserva y cuantos."""

    addon_id: str = Field(..., min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
    quantity: int = Field(..., ge=1, le=ADDON_MAX_QUANTITY)


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
    # Versiones aceptadas, tal como las dio ``GET /public/legal/versions``
    # (PV-09, 2026-09-25). Opcionales para no romper el front actual; si
    # vienen tienen que ser las vigentes (409 LEGAL_VERSION_MISMATCH).
    terms_version: LegalVersion | None = None
    privacy_version: LegalVersion | None = None
    # Adicionales del servicio (decision de Mateo, 2026-10-14). Aditivo: sin
    # el campo la reserva es la de siempre. Un id que no es del servicio, uno
    # repetido o una cantidad mayor al maximo es 422 ``ADDON_UNAVAILABLE``.
    addons: list[PublicAddonChoice] = Field(
        default_factory=list, max_length=ADDONS_PER_SERVICE
    )
    # Varios servicios del mismo profesional en un turno (decision de Mateo,
    # 2026-10-16). Aditivo: vacio es la reserva de siempre. ``service_id`` es
    # el principal y estos los demas, en el orden elegido. Tope duro de la
    # entrada (regla 9); el de producto (3 servicios en total) sale con 422
    # ``TOO_MANY_SERVICES`` y el flag apagado con 422 ``MULTI_SERVICE_DISABLED``.
    extra_service_ids: list[ExtraServiceId] = Field(
        default_factory=list, max_length=EXTRA_SERVICES_INPUT_MAX
    )

    @model_validator(mode="before")
    @classmethod
    def blank_email_is_none(cls, data: Any) -> Any:
        return blank_client_email_to_none(data)

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
        # Tope ancho (2 anios): 9999-12-31 desbordaba ``starts_at + duracion``
        # (500). No el horizonte de 120 dias: el "Nuevo turno" del panel
        # reserva por aca con fecha libre; al cliente lo acota la grilla.
        if not within_max_ahead(value, MAX_BOOKING_AHEAD):
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


class PublicBookingExtraService(BaseModel):
    """Un servicio extra congelado del turno (``extra_services_snapshot``)."""

    public_id: str
    name: str
    duration_minutes: int
    # Precio de lista congelado al reservar, sin descuento (para detallar el
    # total en la pantalla de exito).
    price: float = 0.0


class PublicBookingAddonLine(BaseModel):
    """Una linea congelada del turno (``appointments.addons_snapshot``)."""

    addon_id: str
    name: str
    unit_price: float
    quantity: int
    amount: float


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
    # Por donde se paga la sena obligatoria (decision de Mateo, 2026-10-03):
    # ``mercadopago`` (``payment_link`` es el checkout) o ``whatsapp`` (la
    # tienda la confirma a mano); None si no hay sena que pagar. Aditivo.
    deposit_channel: Literal["mercadopago", "whatsapp"] | None = None
    # Hasta cuando se puede pagar la sena (UTC): despues el turno se libera.
    # Por WhatsApp, hasta 2 h antes del turno. Aditivo.
    deposit_deadline: datetime | None = None
    payment_status: str | None = None
    payment_link: str | None = None
    payment_public_id: str | None = None
    payment_amount: float | None = None
    promotion_code: str | None = None
    service_price: float | None = None
    discount_amount: float | None = None
    # El total del turno: servicio (con la promo, si la hubo) + adicionales.
    final_price: float | None = None
    # Aditivos (2026-10-14): lo elegido y su importe, ya incluido en
    # ``final_price``.
    addons: list[PublicBookingAddonLine] = Field(default_factory=list)
    addons_amount: float = 0.0
    # Aditivos (2026-10-16): los servicios extra del turno (vacio si no hay) y
    # la etiqueta de todos ("Corte + Barba"; el nombre solo sin extras).
    extra_services: list[PublicBookingExtraService] = Field(default_factory=list)
    services_label: str = ""
    # La parte de ``final_price`` que son servicios extra (su lista, sin
    # descuento); ``service_price`` sigue siendo el principal.
    extra_services_amount: float = 0.0

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
    # El total sobre el que se calcula la sena: servicio (con promo) +
    # adicionales.
    price: float
    payments_enabled: bool
    online_payment_mandatory: bool
    # Aditivo (2026-10-14): la parte de ``price`` que son adicionales.
    addons_amount: float = 0.0
    # Aditivo (2026-10-16): la parte de ``price`` que son servicios extra (su
    # precio de lista, sin descuento).
    extra_services_amount: float = 0.0
    # Aditivo (decision de Mateo, 2026-10-20): el turno empieza a mas de
    # ``FAR_BOOKING_DAYS`` dias locales. Con sena obligatoria, ahi solo se
    # paga por Mercado Pago (``online_payment_mandatory`` ya lo refleja).
    far_booking: bool = False
    # Aditivo (2026-10-20): el codigo con el que el alta rechazaria esta
    # reserva por su canal de cobro, pague como pague el cliente
    # (``FAR_BOOKING_UNAVAILABLE`` o ``DEPOSIT_CHANNEL_UNAVAILABLE``); None si
    # se puede reservar.
    booking_blocked_code: str | None = None


class PublicPromotionPreviewResponse(BaseModel):
    code: str
    title: str
    promotion_type: str
    base_amount: float
    discount_amount: float
    final_amount: float


class ClientAppointmentItem(BaseModel):
    public_id: str
    # Ids publicos para pedir la grilla al reprogramar (D-20260930-06): el
    # ``public_id`` del servicio y el id publico del profesional, los mismos
    # que usa la reserva publica.
    service_id: str
    service_name: str
    staff_id: str
    staff_name: str
    starts_at: datetime
    ends_at: datetime
    status: str
    notes: Optional[str] = None
    custom_fields: dict[str, str] = Field(default_factory=dict)
    can_cancel: bool
    can_reschedule: bool
    # Aditivos (2026-10-16): los servicios extra y la etiqueta del turno.
    extra_services: list[PublicBookingExtraService] = Field(default_factory=list)
    services_label: str = ""


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
        # Mismo tope ancho: "Mis turnos" reprograma con fecha libre y un turno
        # que ya esta mas alla de +120 dias se tiene que poder mover.
        if not within_max_ahead(value, MAX_BOOKING_AHEAD):
            raise ValueError("La fecha esta fuera del rango de reservas")
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
