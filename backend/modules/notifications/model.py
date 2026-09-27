from datetime import datetime, timezone
import enum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.models import BaseEntity


class NotificationType(str, enum.Enum):
    """Eventos que el dueño de la tienda necesita ver en el panel."""

    APPOINTMENT_PENDING_CONFIRMATION = "appointment.pending_confirmation"
    PAYMENT_APPROVED = "payment.approved"
    # Pago acreditado de un turno que ya se habia liberado (S-16): la plata
    # entro pero el turno no revive; el dueno decide devolverla o reasignarla.
    PAYMENT_ON_RELEASED_APPOINTMENT = "payment.received_on_released_appointment"
    # Plata que entro por un link reemplazado (regenerado o re-tarifado): no
    # se aplica al cobro vigente, pero el dueno se entera (perf/f4-pay).
    PAYMENT_ON_REPLACED_LINK = "payment.received_on_replaced_link"
    # Registro de un reembolso hecho fuera de Shifty (B2-05 / B2-17).
    PAYMENT_REFUNDED = "payment.refunded"
    # Contracargo avisado por Mercado Pago (AUD2-B2-04): la plata volvio al
    # cliente sin que la tienda la devolviera, asi que el aviso es otro.
    PAYMENT_CHARGED_BACK = "payment.charged_back"
    # Disputa abierta en Mercado Pago sobre un cobro ya acreditado (V-diff de
    # AUD2-B2-04): el estado del cobro no cambia, la plata queda retenida.
    PAYMENT_IN_MEDIATION = "payment.in_mediation"
    WAITLIST_SLOT_RELEASED = "waitlist.slot_released"
    SUBSCRIPTION_EXPIRING = "subscription.expiring"
    APPOINTMENT_CANCELLED_BY_CLIENT = "appointment.cancelled_by_client"


class Notification(BaseEntity):
    __tablename__ = "notifications"
    # El contador de no leidas del panel (cada 60 s por usuario) solo recorre
    # las no leidas de la tienda (F1-14, migracion a6c8e0f2b4d7). Reemplaza a
    # los indices planos de ``store_id`` (prefijo de
    # ``ix_notifications_store_created``) y de ``read_at`` (sin uso).
    __table_args__ = (
        Index(
            "ix_notifications_store_unread",
            "store_id",
            postgresql_where=text("read_at IS NULL"),
            sqlite_where=text("read_at IS NULL"),
        ),
        # Leidas: las que purga la retencion (F1-19, migracion e5f7a9b1c3d6).
        Index(
            "ix_notifications_read_history",
            "read_at",
            postgresql_where=text("read_at IS NOT NULL"),
            sqlite_where=text("read_at IS NOT NULL"),
        ),
    )

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"))
    type: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    appointment_id: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def mark_read(self) -> None:
        self.read_at = self.read_at or datetime.now(timezone.utc)


__all__ = ["Notification", "NotificationType"]
