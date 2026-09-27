"""Constancias legales: terminos B2B aceptados y bajas de mails promocionales."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
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


class MarketingOptOut(BaseEntity):
    """Baja de un cliente de los mails promocionales de UNA tienda (art. 27
    Ley 25.326, 2026-09-25). Hoy cubre el mail "volve a reservar"; los
    transaccionales (registro, confirmacion, recordatorios, cancelaciones) no
    se tocan. Una fila por cliente y tienda: darse de baja dos veces no
    cambia la fecha original.
    """

    __tablename__ = "marketing_opt_outs"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "client_id", name="uq_marketing_opt_outs_store_client"
        ),
    )

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"))
    client_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    opted_out_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
