from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional, cast

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
        client_name = kwargs.pop("client_name", None)
        client_email = kwargs.pop("client_email", None)
        client_phone = kwargs.pop("client_phone", None)
        # `status=` es el nombre publico que usan los repositorios al crear.
        if "status" in kwargs:
            kwargs["_status"] = kwargs.pop("status")
        super().__init__(**kwargs)
        if client_name is not None:
            self.client_name = client_name
        if client_email is not None:
            self.client_email = client_email
        if client_phone is not None:
            self.client_phone = client_phone

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

    @property
    def client_name(self) -> str:
        override = cast(str | None, getattr(self, "_client_name_override", None))
        if override:
            return override
        client = self.__dict__.get("client")
        if client is not None:
            first_name = cast(str | None, getattr(client, "first_name", None))
            last_name = cast(str | None, getattr(client, "last_name", None))
            value = " ".join(
                part.strip()
                for part in (first_name, last_name)
                if part and part.strip()
            ).strip()
            if value:
                return value
            email = cast(str | None, getattr(client, "email", None))
            if email:
                return email
        return ""

    @client_name.setter
    def client_name(self, value: str | None) -> None:
        self._client_name_override = (value or "").strip()

    @property
    def client_email(self) -> Optional[str]:
        override = cast(str | None, getattr(self, "_client_email_override", None))
        if override is not None:
            return override
        client = self.__dict__.get("client")
        if client is not None:
            return cast(str | None, getattr(client, "email", None))
        return None

    @client_email.setter
    def client_email(self, value: str | None) -> None:
        self._client_email_override = value.strip() if isinstance(value, str) else value

    @property
    def client_phone(self) -> Optional[str]:
        override = cast(str | None, getattr(self, "_client_phone_override", None))
        if override is not None:
            return override
        client = self.__dict__.get("client")
        if client is not None:
            return cast(str | None, getattr(client, "phone", None))
        return None

    @client_phone.setter
    def client_phone(self, value: str | None) -> None:
        self._client_phone_override = value.strip() if isinstance(value, str) else value

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

    @property
    def ends_at_derived(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_minutes)

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'pending_payment', 'confirmed', 'absent', 'completed', 'cancelled', 'expired')",
            name="check_appointment_status_v3",
        ),
    )
