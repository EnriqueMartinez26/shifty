from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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


class UnsubscribeResponse(BaseModel):
    """Confirmacion neutra de la baja: no dice de quien ni de que tienda."""

    status: str
