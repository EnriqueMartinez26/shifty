from datetime import datetime
from typing import Any
from core.exceptions import AppointmentConflictException, BlockedScheduleException


class SchedulingDomainService:
    """
    Domain Service para la validación de reglas de negocio en la agenda.
    Esta clase es pura lógica de dominio y no tiene dependencias de infraestructura (IO/DB).
    """

    def validate_availability(
        self,
        *,
        requested_start: datetime,
        requested_end: datetime,
        conflicting_appointment: Any | None = None,
        overlapping_block: Any | None = None,
        suggestion: datetime | None = None,
    ) -> None:
        """
        Verifica si un profesional está disponible para un rango horario.
        Lanza excepciones de dominio específicas con feedback enriquecido (UX).
        """
        # 1. Prioridad: Bloqueos manuales de agenda (Constraints de Don Norman)
        if overlapping_block:
            raise BlockedScheduleException(
                reason=getattr(overlapping_block, "note", "Bloqueo de agenda"),
                block_start=overlapping_block.starts_at,
                block_end=overlapping_block.ends_at,
                suggestion=suggestion,
            )

        # 2. Conflictos con otros turnos (Feedback & Prevention)
        if conflicting_appointment:
            raise AppointmentConflictException(
                conflict_start=conflicting_appointment.starts_at,
                conflict_end=conflicting_appointment.ends_at,
                suggestion=suggestion,
            )

        # Aquí se podrían añadir más reglas, como:
        # - Verificar si está dentro del horario laboral del staff.
        # - Verificar si el staff tiene la especialidad necesaria.
        # - Verificar si el tiempo de buffer se respeta.
