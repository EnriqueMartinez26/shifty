from infrastructure.persistence.models.appointment import AppointmentModel as Appointment
# Keep old status enum if needed by legacy code
import enum

class AppointmentStatus(str, enum.Enum):
    PENDING   = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    ABSENT    = "absent"

    def can_transition_to(self, next_status: "AppointmentStatus") -> bool:
        allowed = {
            AppointmentStatus.PENDING: {AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED},
            AppointmentStatus.CONFIRMED: {AppointmentStatus.COMPLETED, AppointmentStatus.CANCELLED, AppointmentStatus.ABSENT},
            AppointmentStatus.CANCELLED: set(),
            AppointmentStatus.COMPLETED: set(),
            AppointmentStatus.ABSENT: set(),
        }
        return next_status in allowed.get(self, set())

