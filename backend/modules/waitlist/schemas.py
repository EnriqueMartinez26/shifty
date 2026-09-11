from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from core.validation import PUBLIC_ID_PATTERN, reject_payload_control_chars


def _normalize_phone(value: str) -> str:
    # Misma normalizacion que la reserva publica (solo digitos).
    cleaned = re.sub(r"[\s\-\(\)\+]", "", value)
    if not cleaned.isdigit():
        raise ValueError(
            "El telefono solo puede contener digitos, espacios o los caracteres: + - ( )"
        )
    return cleaned


class WaitlistJoinRequest(BaseModel):
    store_public_id: str = Field(
        ..., min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN
    )
    service_id: str = Field(..., min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
    staff_id: Optional[str] = Field(
        default=None, max_length=64, pattern=PUBLIC_ID_PATTERN
    )
    window_starts_at: datetime
    window_ends_at: datetime
    client_name: str = Field(..., min_length=1, max_length=100)
    client_phone: str = Field(..., min_length=6, max_length=30)
    client_email: Optional[EmailStr] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=300)

    @field_validator("client_phone")
    @classmethod
    def phone_digits(cls, value: str) -> str:
        return _normalize_phone(value)

    @model_validator(mode="after")
    def reject_control_chars_in_text(self) -> "WaitlistJoinRequest":
        """Regla 19: nada de NUL, bidi ni zero-width en texto libre publico.

        Estos textos viajan al mail de la oferta y al link wa.me del panel.
        """
        self.client_name = reject_payload_control_chars(self.client_name)
        self.notes = reject_payload_control_chars(self.notes)
        return self

    @model_validator(mode="after")
    def window_is_valid(self) -> "WaitlistJoinRequest":
        if self.window_ends_at <= self.window_starts_at:
            raise ValueError("La ventana termina antes de empezar")
        if (self.window_ends_at - self.window_starts_at).days > 60:
            raise ValueError("La ventana no puede superar los 60 dias")
        return self


class WaitlistClientQuery(BaseModel):
    store_public_id: str = Field(
        ..., min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN
    )
    phone: str = Field(..., min_length=6, max_length=30)

    @field_validator("phone")
    @classmethod
    def phone_digits(cls, value: str) -> str:
        return _normalize_phone(value)


class WaitlistEntryResponse(BaseModel):
    public_id: str
    status: str
    service_id: str
    service_name: str
    staff_id: Optional[str]
    staff_name: Optional[str]
    window_starts_at: datetime
    window_ends_at: datetime
    client_name: str
    # Solo para administradores; el cliente ve el suyo.
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    notes: Optional[str] = None
    notified_at: Optional[datetime] = None
    offer_expires_at: Optional[datetime] = None
    offered_starts_at: Optional[datetime] = None
    offered_staff_id: Optional[str] = None
    created_at: datetime


class WaitlistBookRequest(BaseModel):
    """El dueno reserva a mano para alguien de la lista (sin antelacion minima)."""

    starts_at: datetime
    staff_id: Optional[str] = Field(
        default=None, max_length=64, pattern=PUBLIC_ID_PATTERN
    )
