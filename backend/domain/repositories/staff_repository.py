from abc import ABC, abstractmethod
from typing import List, Optional
from domain.entities.staff import Staff


class IStaffRepository(ABC):
    """Abstract interface for staff data access."""

    @abstractmethod
    async def find_by_id(self, id: str) -> Optional[Staff]:
        """Find a staff member by ID."""
        pass

    @abstractmethod
    async def find_all(self, store_id: str) -> List[Staff]:
        """Find all staff members for a specific store."""
        pass

    @abstractmethod
    async def save(self, staff: Staff) -> Staff:
        """Save a new or existing staff member."""
        pass

    @abstractmethod
    async def delete(self, id: str) -> None:
        """Delete a staff member."""
        pass
