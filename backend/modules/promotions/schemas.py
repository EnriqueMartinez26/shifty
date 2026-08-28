from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

# Techos de los enteros expuestos por la API.
#
# Las columnas son INTEGER de PostgreSQL: cualquier valor por encima de 2^31-1
# revienta al guardar y sale como 500. Ademas de evitar eso, los topes reflejan
# maximos con sentido de negocio.
MAX_HORAS_ANIO = 8760  # un anio
MAX_MINUTOS_DIA = 1440  # un dia
MAX_ELEMENTOS_PLAN = 10_000
MAX_USOS_CUPON = 1_000_000


PROMOTION_CODE_PATTERN = r"^[A-Za-z0-9_-]{3,30}$"


def _normalize_code(value: str) -> str:
    return value.strip().upper()


class PromotionBase(BaseModel):
    code: str = Field(..., min_length=3, max_length=30, pattern=PROMOTION_CODE_PATTERN)
    title: str = Field(..., min_length=2, max_length=120)
    description: str | None = Field(None, max_length=1000)
    promotion_type: str = Field(default="percent", pattern=r"^(percent|fixed)$")
    value: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    min_service_amount: Decimal | None = Field(
        None, ge=0, max_digits=12, decimal_places=2
    )
    max_uses: int | None = Field(None, gt=0, le=MAX_USOS_CUPON)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return _normalize_code(value)

    @model_validator(mode="after")
    def validate_window(self) -> "PromotionBase":
        if self.valid_from and self.valid_until and self.valid_from >= self.valid_until:
            raise ValueError("La vigencia de la promocion es invalida")
        if self.promotion_type == "percent" and self.value > Decimal("100"):
            raise ValueError("El descuento porcentual no puede superar 100")
        return self


class PromotionCreate(PromotionBase):
    pass


class PromotionUpdate(BaseModel):
    code: str | None = Field(
        None, min_length=3, max_length=30, pattern=PROMOTION_CODE_PATTERN
    )
    title: str | None = Field(None, min_length=2, max_length=120)
    description: str | None = Field(None, max_length=1000)
    promotion_type: str | None = Field(None, pattern=r"^(percent|fixed)$")
    value: Decimal | None = Field(None, gt=0, max_digits=12, decimal_places=2)
    min_service_amount: Decimal | None = Field(
        None, ge=0, max_digits=12, decimal_places=2
    )
    max_uses: int | None = Field(None, gt=0, le=MAX_USOS_CUPON)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_code(value)

    @model_validator(mode="after")
    def validate_window(self) -> "PromotionUpdate":
        if self.valid_from and self.valid_until and self.valid_from >= self.valid_until:
            raise ValueError("La vigencia de la promocion es invalida")
        if (
            self.promotion_type == "percent"
            and self.value is not None
            and self.value > Decimal("100")
        ):
            raise ValueError("El descuento porcentual no puede superar 100")
        return self


class PromotionResponse(BaseModel):
    public_id: str
    code: str
    title: str
    description: str | None
    promotion_type: str
    value: Decimal
    min_service_amount: Decimal | None
    max_uses: int | None
    current_uses: int
    valid_from: datetime | None
    valid_until: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PromotionQuoteResponse(BaseModel):
    code: str
    title: str
    promotion_type: str
    base_amount: Decimal
    discount_amount: Decimal
    final_amount: Decimal
