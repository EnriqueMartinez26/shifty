from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional, cast

import ulid
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence.models.base import Base

if TYPE_CHECKING:
    from modules.appointments.model import AppointmentStatus


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
    status: Mapped[str] = mapped_column(String(50), default="pending")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    notes_staff: Mapped[Optional[str]] = mapped_column(Text)
    intake_answers: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
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
        super().__init__(**kwargs)
        if client_name is not None:
            self.client_name = client_name
        if client_email is not None:
            self.client_email = client_email
        if client_phone is not None:
            self.client_phone = client_phone

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
        allowed_transitions = {
            "pending": {"confirmed", "cancelled", "pending_payment"},
            "pending_payment": {"confirmed", "cancelled", "expired"},
            "confirmed": {"completed", "cancelled", "absent"},
            "cancelled": set(),
            "completed": set(),
            "absent": set(),
            "expired": set(),
        }

        if attempted == current:
            return

        if attempted not in allowed_transitions.get(current, set()):
            raise InvalidStatusTransitionException(current=current, attempted=attempted)

        self.status = attempted
        now = datetime.now(timezone.utc)
        if attempted == "cancelled":
            self.cancelled_at = now
        elif attempted == "completed":
            self.completed_at = now
        self.updated_at = now

    @property
    def ends_at_derived(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_minutes)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'pending_payment', 'confirmed', 'absent', 'completed', 'cancelled', 'expired')",
            name="check_appointment_status_v3",
        ),
    )
