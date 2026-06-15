from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from domain.value_objects.time_slot import TimeSlot


class AppointmentStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    ABSENT = "ABSENT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass
class Appointment:
    """Domain entity representing a booking appointment."""

    id: str
    service_id: str
    staff_id: str
    store_id: str
    time_slot: TimeSlot
    client_name: str
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    status: AppointmentStatus = AppointmentStatus.PENDING
    notes: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def confirm(self):
        if self.status == AppointmentStatus.CANCELLED:
            raise ValueError("Cannot confirm a cancelled appointment")
        self.status = AppointmentStatus.CONFIRMED
        self.updated_at = datetime.now(timezone.utc)

    def cancel(self):
        if self.status == AppointmentStatus.COMPLETED:
            raise ValueError("Cannot cancel a completed appointment")
        self.status = AppointmentStatus.CANCELLED
        self.updated_at = datetime.now(timezone.utc)

    def complete(self):
        if self.status != AppointmentStatus.CONFIRMED:
            raise ValueError("Can only complete confirmed appointments")
        self.status = AppointmentStatus.COMPLETED
        self.updated_at = datetime.now(timezone.utc)

    def mark_absent(self):
        if self.status != AppointmentStatus.CONFIRMED:
            raise ValueError("Can only mark absent confirmed appointments")
        self.status = AppointmentStatus.ABSENT
        self.updated_at = datetime.now(timezone.utc)

    def reschedule(self, new_time_slot: TimeSlot):
        if self.status in [AppointmentStatus.COMPLETED, AppointmentStatus.CANCELLED]:
            raise ValueError(f"Cannot reschedule a {self.status.value} appointment")
        self.time_slot = new_time_slot
        self.updated_at = datetime.utcnow()
