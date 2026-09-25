from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from core.validation import reject_control_chars


class LegalVersionsResponse(BaseModel):
    """Versiones vigentes de los textos que acepta el cliente del portal."""

    terms_version: str
    privacy_version: str


class StoreTermsAcceptanceResponse(BaseModel):
    """Una aceptacion de los terminos B2B. Sin la IP ni su hash."""

    terms_version: str
    accepted_at: datetime
    # public_id del usuario que acepto.
    accepted_by: str


class StoreTermsStatusResponse(BaseModel):
    current_version: str
    current_version_accepted: bool
    latest: StoreTermsAcceptanceResponse | None = None


class UnsubscribeRequest(BaseModel):
    """Token del link de baja (``modules/legal/unsubscribe.py``)."""

    token: str = Field(min_length=1, max_length=256)

    @field_validator("token")
    @classmethod
    def no_control_chars(cls, value: str) -> str:
        # Regla 19 (texto de un anonimo): NUL, bidi y zero-width son 422.
        # Un token raro sin esos caracteres llega al service y es 400.
        reject_control_chars(value)
        return value


class UnsubscribeResponse(BaseModel):
    """Confirmacion neutra de la baja: no dice de quien ni de que tienda."""

    status: str
