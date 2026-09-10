"""Lista de espera: quien quiere un turno que hoy no tiene cupo.

Una entrada es "cliente + servicio + profesional (o cualquiera) + ventana
deseada". Cuando se libera un cupo que encaja, el consumidor del outbox se lo
ofrece a UNA persona por vez (``offered``) durante N minutos; si no reserva,
pasa a la siguiente. La exclusividad es blanda: el cupo sigue publicado para
cualquiera y quien reserva primero gana por el lock y la exclusion que ya
existen. No hay endpoint de "reclamar": reservar es reservar.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models import BaseEntity


class WaitlistStatus(str, enum.Enum):
    WAITING = "waiting"
    OFFERED = "offered"
    BOOKED = "booked"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


OPEN_WAITLIST_STATUSES: tuple[str, ...] = (
    WaitlistStatus.WAITING.value,
    WaitlistStatus.OFFERED.value,
)

_OPEN_SQL = "status IN ('waiting', 'offered')"


class WaitlistEntry(BaseEntity):
    __tablename__ = "waitlist_entries"

    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    client_name: Mapped[str] = mapped_column(String(100))
    client_phone: Mapped[str] = mapped_column(String(30), index=True)
    client_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), index=True)
    # Nulo = "cualquier profesional".
    staff_id: Mapped[str | None] = mapped_column(
        ForeignKey("staff.id"), nullable=True, index=True
    )
    window_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(20), default=WaitlistStatus.WAITING.value, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Oferta vigente (o la ultima que dejo pasar): sirve para no volver a
    # ofrecerle el mismo cupo y para que el dueno vea que se le aviso.
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    offer_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    offered_staff_id: Mapped[str | None] = mapped_column(String, nullable=True)
    offered_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    offered_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('waiting', 'offered', 'booked', 'cancelled', 'expired')",
            name="ck_waitlist_status",
        ),
        CheckConstraint("window_ends_at > window_starts_at", name="ck_waitlist_window"),
        Index(
            "ix_waitlist_store_status_window",
            "store_id",
            "status",
            "window_starts_at",
        ),
        # Un mismo telefono no se anota dos veces para lo mismo mientras la
        # entrada sigue abierta; una vez reservada o cancelada puede volver.
        Index(
            "uq_waitlist_open_entry",
            "store_id",
            "client_phone",
            "service_id",
            "window_starts_at",
            unique=True,
            postgresql_where=text(_OPEN_SQL),
            sqlite_where=text(_OPEN_SQL),
        ),
    )

    @property
    def public_id(self) -> str:
        return self.id

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_WAITLIST_STATUSES


__all__ = ["OPEN_WAITLIST_STATUSES", "WaitlistEntry", "WaitlistStatus"]
