from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from infrastructure.persistence.models.base import Base
import ulid

class AppointmentModel(Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True, default=lambda: str(ulid.ULID()))
    service_id: Mapped[str] = mapped_column(String, ForeignKey("services.id"), index=True)
    staff_id: Mapped[str] = mapped_column(String, ForeignKey("staff.id"), index=True)
    store_id: Mapped[str] = mapped_column(String, ForeignKey("stores.id"), index=True)
    client_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_minutes: Mapped[int] = mapped_column()
    client_name: Mapped[str] = mapped_column(String(255))
    client_email: Mapped[Optional[str]] = mapped_column(String(255))
    client_phone: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    notes_staff: Mapped[Optional[str]] = mapped_column(Text)
    intake_answers: Mapped[dict | None] = mapped_column(JSON, default=dict)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    service = relationship("Service")
    staff = relationship("StaffModel")
    client = relationship("UserModel")

    @property
    def public_id(self) -> str:
        return self.id

    def apply_status_transition(self, new_status) -> None:
        from core.exceptions import InvalidStatusTransitionException

        attempted = new_status.value if hasattr(new_status, "value") else str(new_status)
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

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'pending_payment', 'confirmed', 'absent', 'completed', 'cancelled', 'expired')",
            name="check_appointment_status_v3"
        ),
    )
