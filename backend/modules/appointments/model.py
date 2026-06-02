import enum

from infrastructure.persistence.models.appointment import AppointmentModel as Appointment


class AppointmentStatus(str, enum.Enum):
    PENDING = "pending"
    PENDING_PAYMENT = "pending_payment"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    ABSENT = "absent"
    EXPIRED = "expired"

    def can_transition_to(self, next_status: "AppointmentStatus") -> bool:
        allowed = {
            AppointmentStatus.PENDING: {
                AppointmentStatus.CONFIRMED,
                AppointmentStatus.CANCELLED,
                AppointmentStatus.PENDING_PAYMENT,
            },
            AppointmentStatus.PENDING_PAYMENT: {
                AppointmentStatus.CONFIRMED,
                AppointmentStatus.CANCELLED,
                AppointmentStatus.EXPIRED,
            },
            AppointmentStatus.CONFIRMED: {
                AppointmentStatus.COMPLETED,
                AppointmentStatus.CANCELLED,
                AppointmentStatus.ABSENT,
            },
            AppointmentStatus.CANCELLED: set(),
            AppointmentStatus.COMPLETED: set(),
            AppointmentStatus.ABSENT: set(),
            AppointmentStatus.EXPIRED: set(),
        }
        return next_status in allowed.get(self, set())
