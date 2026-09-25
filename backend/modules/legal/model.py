"""Aceptacion de los terminos B2B por la tienda (L1, O-6 y 4.1; 2026-09-25)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from core.models import BaseEntity


class StoreTermsAcceptance(BaseEntity):
    """Constancia de que el admin de la tienda acepto una version de los
    terminos B2B. Solo se agrega: una version nueva es una fila nueva y la
    vieja queda como evidencia de lo que rigio antes.

    ``ip_hash``: HMAC de la IP con clave derivada de ``SECRET_KEY``
    (``core.security.hash_ip``); la IP en claro no se guarda.
    """

    __tablename__ = "store_terms_acceptances"
    __table_args__ = (
        Index("ix_store_terms_acceptances_store_accepted", "store_id", "accepted_at"),
    )

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    terms_version: Mapped[str] = mapped_column(String(20))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
