from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from core.validation import PUBLIC_ID_PATTERN, SLUG_PATTERN, reject_unsafe_url
from modules.users.model import UserRole

# Techos de los enteros expuestos por la API.
#
# Las columnas son INTEGER de PostgreSQL: cualquier valor por encima de 2^31-1
# revienta al guardar y sale como 500. Ademas de evitar eso, los topes reflejan
# maximos con sentido de negocio.
MAX_HORAS_ANIO = 8760  # un anio
MAX_MINUTOS_DIA = 1440  # un dia
MAX_ELEMENTOS_PLAN = 10_000
MAX_USOS_CUPON = 1_000_000


CouponType = Literal["percent", "fixed"]


class StoreCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100, pattern=SLUG_PATTERN)
    logo_url: str | None = Field(None, max_length=500)
    primary_color: str = Field(default="#000000", max_length=20)
    cancellation_hours: int = Field(default=24, ge=0, le=MAX_HORAS_ANIO)
    buffer_minutes: int = Field(default=0, ge=0, le=MAX_MINUTOS_DIA)
    send_email_confirmation: bool = True
    send_email_reminders: bool = True

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, value: str | None) -> str | None:
        return reject_unsafe_url(value)


class StoreGlobalUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    slug: str | None = Field(None, min_length=2, max_length=100, pattern=SLUG_PATTERN)
    logo_url: str | None = Field(None, max_length=500)
    primary_color: str | None = Field(None, max_length=20)
    cancellation_hours: int | None = Field(None, ge=0, le=MAX_HORAS_ANIO)
    buffer_minutes: int | None = Field(None, ge=0, le=MAX_MINUTOS_DIA)
    send_email_confirmation: bool | None = None
    send_email_reminders: bool | None = None
    is_active: bool | None = None

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, value: str | None) -> str | None:
        return reject_unsafe_url(value)


class StoreGlobalResponse(BaseModel):
    public_id: str
    name: str
    slug: str
    logo_url: str | None
    primary_color: str
    cancellation_hours: int
    buffer_minutes: int
    send_email_confirmation: bool
    send_email_reminders: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StoreTableResponse(StoreGlobalResponse):
    admins_count: int
    users_count: int
    active_users_count: int
    has_subscription: bool
    subscription_status: str | None
    current_plan_name: str | None
    current_period_end: datetime | None
    last_redemption_at: datetime | None


class StoreAdminCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=50)


class UserGlobalUpdate(BaseModel):
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=50)
    role: UserRole | None = None
    password: str | None = Field(None, min_length=8, max_length=128)
    is_active: bool | None = None


class GlobalAdminUpdate(BaseModel):
    is_global_admin: bool


class UserGlobalResponse(BaseModel):
    public_id: str
    email: EmailStr
    first_name: str | None
    last_name: str | None
    phone: str | None
    role: str
    store_id: str
    is_active: bool
    is_global_admin: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PlanCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    description: str | None = Field(None, max_length=2000)
    price: Decimal = Field(..., ge=0, le=10_000_000)
    currency: str = Field(default="ARS", min_length=3, max_length=10)
    billing_interval: str = Field(default="monthly", min_length=3, max_length=20)
    max_staff: int | None = Field(None, ge=0, le=MAX_ELEMENTOS_PLAN)
    max_services: int | None = Field(None, ge=0, le=MAX_ELEMENTOS_PLAN)


class PlanUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    description: str | None = Field(None, max_length=2000)
    price: Decimal | None = Field(None, ge=0, le=10_000_000)
    currency: str | None = Field(None, min_length=3, max_length=10)
    billing_interval: str | None = Field(None, min_length=3, max_length=20)
    max_staff: int | None = Field(None, ge=0, le=MAX_ELEMENTOS_PLAN)
    max_services: int | None = Field(None, ge=0, le=MAX_ELEMENTOS_PLAN)
    is_active: bool | None = None


class PlanResponse(PlanCreate):
    public_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StoreSubscriptionCreate(BaseModel):
    plan_id: str = Field(..., min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
    status: str = Field(default="active", min_length=3, max_length=30)
    base_amount: Decimal | None = Field(None, ge=0, le=10_000_000)
    currency: str | None = Field(None, min_length=3, max_length=10)
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None


class StoreSubscriptionResponse(BaseModel):
    public_id: str
    store_id: str
    plan_id: str
    status: str
    base_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    currency: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    coupon_id: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AppliedCouponSummary(BaseModel):
    public_id: str
    code: str
    coupon_type: str
    value: Decimal
    currency: str | None
    is_active: bool

    class Config:
        from_attributes = True


class StoreSubscriptionOverviewResponse(StoreSubscriptionResponse):
    plan_name: str | None = None
    billing_interval: str | None = None
    max_staff: int | None = None
    max_services: int | None = None
    applied_coupon: AppliedCouponSummary | None = None


class CouponCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=50)
    coupon_type: CouponType
    value: Decimal = Field(..., gt=0, le=10_000_000)
    currency: str | None = Field(None, min_length=3, max_length=10)
    max_uses: int | None = Field(None, ge=1, le=MAX_USOS_CUPON)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    one_time_per_store: bool = True
    description: str | None = Field(None, max_length=2000)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_coupon(self) -> "CouponCreate":
        if self.coupon_type == "percent" and self.value > 100:
            raise ValueError("El porcentaje de descuento no puede superar 100")
        if self.valid_from and self.valid_until and self.valid_from >= self.valid_until:
            raise ValueError("valid_from debe ser anterior a valid_until")
        return self


class CouponUpdate(BaseModel):
    code: str | None = Field(None, min_length=3, max_length=50)
    coupon_type: CouponType | None = None
    value: Decimal | None = Field(None, gt=0, le=10_000_000)
    currency: str | None = Field(None, min_length=3, max_length=10)
    max_uses: int | None = Field(None, ge=1, le=MAX_USOS_CUPON)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    one_time_per_store: bool | None = None
    description: str | None = Field(None, max_length=2000)
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value


class CouponResponse(BaseModel):
    public_id: str
    code: str
    coupon_type: str
    value: Decimal
    currency: str | None
    max_uses: int | None
    current_uses: int
    valid_from: datetime | None
    valid_until: datetime | None
    one_time_per_store: bool
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CouponRedeemRequest(BaseModel):
    coupon_code: str = Field(
        ..., min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_-]+$"
    )

    @field_validator("coupon_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class CouponRedemptionResponse(BaseModel):
    public_id: str
    coupon_id: str
    store_id: str
    subscription_id: str | None
    redeemed_by_id: str | None
    code_snapshot: str
    coupon_type_snapshot: str
    value_snapshot: Decimal
    base_amount: Decimal
    discount_amount: Decimal
    final_amount: Decimal
    currency: str
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogResponse(BaseModel):
    public_id: str
    created_at: datetime
    actor_email: str | None
    resource_type: str
    action: str
    payload_before: dict[str, Any] | list[Any] | str | int | float | bool | None
    payload_after: dict[str, Any] | list[Any] | str | int | float | bool | None
    context: str | None


class StoreUsersOverviewResponse(BaseModel):
    admins: list[UserGlobalResponse]
    users: list[UserGlobalResponse]
    admins_count: int
    users_count: int
    active_users_count: int


class StoreOverviewResponse(BaseModel):
    store: StoreGlobalResponse
    users: StoreUsersOverviewResponse
    subscription: StoreSubscriptionOverviewResponse | None
    recent_redemptions: list[CouponRedemptionResponse]
