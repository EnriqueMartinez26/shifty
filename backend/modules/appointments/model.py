import enum

from infrastructure.persistence.models.appointment import (
    AppointmentModel as Appointment,
)


class AppointmentStatus(str, enum.Enum):
    PENDING = "pending"
    PENDING_PAYMENT = "pending_payment"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    ABSENT = "absent"
    EXPIRED = "expired"

    def can_transition_to(self, next_status: "AppointmentStatus") -> bool:
        """Consulta si la transicion es legal, sin aplicarla.

        Delega en ``ALLOWED_STATUS_TRANSITIONS``, la unica fuente de verdad del
        grafo. Antes esto era una segunda copia del diccionario: coincidian por
        disciplina y los tests validaban la copia que produccion nunca ejecuta.
        """
        from infrastructure.persistence.models.appointment import (
            ALLOWED_STATUS_TRANSITIONS,
        )

        return next_status.value in ALLOWED_STATUS_TRANSITIONS.get(self.value, set())


__all__ = ["Appointment", "AppointmentStatus"]
