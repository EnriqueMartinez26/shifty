from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

import ulid
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence.models.base import Base

if TYPE_CHECKING:
    from modules.appointments.model import AppointmentStatus


# Unica fuente de verdad del grafo de transiciones del turno.
# Los estados terminales mapean a conjuntos vacios: son absorbentes.
ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"confirmed", "cancelled", "pending_payment", "expired"},
    "pending_payment": {"confirmed", "cancelled", "expired"},
    "confirmed": {"completed", "cancelled", "absent"},
    "cancelled": set(),
    "completed": set(),
    "absent": set(),
    "expired": set(),
}


class AppointmentModel(Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, index=True, default=lambda: str(ulid.ULID())
    )
    service_id: Mapped[str] = mapped_column(
        String, ForeignKey("services.id"), index=True
    )
    staff_id: Mapped[str] = mapped_column(String, ForeignKey("staff.id"), index=True)
    store_id: Mapped[str] = mapped_column(String, ForeignKey("stores.id"), index=True)
    client_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), index=True
    )
    # Snapshot de contacto congelado al reservar: no se re-deriva del
    # usuario vinculado despues. Si el cliente cambia nombre/email/telefono,
    # el turno ya reservado conserva lo que valia al momento de la reserva.
    client_name: Mapped[str] = mapped_column(String(255))
    client_email: Mapped[Optional[str]] = mapped_column(String(255))
    client_phone: Mapped[Optional[str]] = mapped_column(String(50))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_minutes: Mapped[int] = mapped_column()
    # Precio congelado al momento de reservar (precio de lista de ese momento).
    # El precio del servicio puede cambiar despues; el turno tiene que valer lo
    # que valia cuando se reservo, no lo que sale hoy. Es el monto que se cobra
    # y el que usa el reporte de ingresos. Nullable por los turnos historicos
    # anteriores a esta columna.
    price_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    # Columna privada: la unica escritura legitima es apply_status_transition().
    # Se expone como hybrid_property de solo lectura, asi que
    # `appointment.status = "completed"` levanta AttributeError en vez de
    # saltearse el grafo. A nivel clase sigue sirviendo para filtrar en queries.
    _status: Mapped[str] = mapped_column("status", String(50), default="pending")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    notes_staff: Mapped[Optional[str]] = mapped_column(Text)
    intake_answers: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), index=True
    )
    # Momento en que el cliente acepto los terminos y la politica de sena de la
    # tienda. Queda registrado como respaldo ante un reclamo.
    terms_accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    # Marcas durables de recordatorio. El job las reclama con
    # ``UPDATE ... WHERE col IS NULL`` (seguro entre workers) y las deja en
    # nulo si el envio falla. Reprogramar crea un turno nuevo, asi que el
    # movido arranca sin marcas.
    reminder_24h_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    reminder_2h_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    # Optimistic locking: SQLAlchemy incrementa esta columna en cada UPDATE y
    # falla con StaleDataError si otra transaccion la movio mientras tanto.
    # Es la red donde el lock pesimista no llega.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    service = relationship("Service")
    staff = relationship("StaffModel")
    client = relationship("UserModel")

    def __init__(self, **kwargs: Any) -> None:
        # `status=` es el nombre publico que usan los repositorios al crear.
        if "status" in kwargs:
            kwargs["_status"] = kwargs.pop("status")
        super().__init__(**kwargs)

    @hybrid_property
    def status(self) -> str:
        return self._status

    @status.inplace.expression
    @classmethod
    def _status_expression(cls) -> Mapped[str]:
        return cls._status

    @property
    def public_id(self) -> str:
        return self.id

    def apply_status_transition(self, new_status: AppointmentStatus | str) -> None:
        from core.exceptions import InvalidStatusTransitionException

        attempted = (
            new_status.value if hasattr(new_status, "value") else str(new_status)
        )
        current = self.status

        if attempted == current:
            return

        if attempted not in ALLOWED_STATUS_TRANSITIONS.get(current, set()):
            raise InvalidStatusTransitionException(current=current, attempted=attempted)

        self._status = attempted
        now = datetime.now(timezone.utc)
        if attempted == "cancelled":
            self.cancelled_at = now
        elif attempted == "completed":
            self.completed_at = now
        self.updated_at = now

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'pending_payment', 'confirmed', 'absent', 'completed', 'cancelled', 'expired')",
            name="check_appointment_status_v3",
        ),
    )
