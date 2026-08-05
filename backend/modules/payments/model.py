from datetime import datetime, timezone
from decimal import Decimal
import enum
from typing import TypeAlias

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models import BaseEntity

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | dict[str, "JsonValue"] | list["JsonValue"]

# Reintentos antes de dar por perdido un webhook que no pudimos resolver.
WEBHOOK_INBOX_MAX_ATTEMPTS = 10


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REFUNDED = "refunded"
    MANUAL_CONFIRMED = "manual_confirmed"


class PaymentGatewayConfig(BaseEntity):
    __tablename__ = "payment_gateway_configs"

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50), default="mercadopago")
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    connection_mode: Mapped[str] = mapped_column(String(20), default="manual")
    oauth_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    oauth_scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oauth_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "store_id", "provider", name="uq_gateway_config_store_provider"
        ),
    )


class Payment(BaseEntity):
    __tablename__ = "payments"

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    appointment_id: Mapped[str] = mapped_column(
        ForeignKey("appointments.id"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50), default="mercadopago")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    original_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    discount_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(10), default="ARS")
    status: Mapped[str] = mapped_column(
        String(50), default=PaymentStatus.PENDING.value, index=True
    )
    promotion_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    preference_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    payment_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_payment_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    transaction_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_payload: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSON, nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "store_id", "appointment_id", name="uq_payments_store_appointment"
        ),
    )


class WebhookInbox(BaseEntity):
    __tablename__ = "webhook_inbox"

    store_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(50), default="mercadopago")
    event_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def mark_processed(self) -> None:
        self.processed_at = datetime.now(timezone.utc)
        self.error = None

    def register_failure(self, reason: str) -> None:
        """Cuenta un intento fallido y abandona el evento al agotar los reintentos.

        No marcamos ``processed_at`` mientras queden intentos: el worker del inbox
        vuelve a tomar la fila y reintenta. Al agotarlos la damos por vencida para
        que deje de reprocesarse y quede visible en ``failed_webhooks``.
        """
        self.attempts = (self.attempts or 0) + 1
        self.error = reason[:1000]
        if self.attempts >= WEBHOOK_INBOX_MAX_ATTEMPTS:
            self.processed_at = datetime.now(timezone.utc)


class OutboxMessage(BaseEntity):
    __tablename__ = "outbox_messages"

    store_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "WEBHOOK_INBOX_MAX_ATTEMPTS",
    "JsonPrimitive",
    "JsonValue",
    "OutboxMessage",
    "Payment",
    "PaymentGatewayConfig",
    "PaymentStatus",
    "WebhookInbox",
]
