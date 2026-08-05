from datetime import datetime, timezone
import enum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.models import BaseEntity


class NotificationType(str, enum.Enum):
    """Eventos que el dueño de la tienda necesita ver en el panel."""

    APPOINTMENT_PENDING_CONFIRMATION = "appointment.pending_confirmation"
    PAYMENT_APPROVED = "payment.approved"


class Notification(BaseEntity):
    __tablename__ = "notifications"

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    type: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    appointment_id: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    def mark_read(self) -> None:
        self.read_at = self.read_at or datetime.now(timezone.utc)


__all__ = ["Notification", "NotificationType"]
