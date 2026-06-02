from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import date
from domain.entities.appointment import Appointment

class IAppointmentRepository(ABC):
    """Abstract interface for appointment data access."""

    @abstractmethod
    async def find_by_id(self, id: str) -> Optional[Appointment]:
        """Find an appointment by its unique identifier."""
        pass

    @abstractmethod
    async def find_by_date(self, store_id: str, date_val: date) -> List[Appointment]:
        """Find all appointments for a specific store and date."""
        pass

    @abstractmethod
    async def find_by_staff_and_date(self, staff_id: str, date_val: date) -> List[Appointment]:
        """Find all appointments for a specific staff member on a specific date."""
        pass

    @abstractmethod
    async def save(self, appointment: Appointment) -> Appointment:
        """Save a new or existing appointment."""
        pass

    @abstractmethod
    async def find_by_idempotency_key(self, key: str) -> Optional[Appointment]:
        """Find an appointment by its idempotency key to prevent duplicates."""
        pass
