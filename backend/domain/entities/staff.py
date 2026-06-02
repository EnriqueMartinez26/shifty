from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

@dataclass
class Staff:
    """Domain entity representing a staff member (professional)."""
    id: str
    first_name: str
    last_name: str
    display_name: str
    email: str
    store_id: str
    service_ids: List[str] = field(default_factory=list)
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def activate(self):
        self.is_active = True
        self.updated_at = datetime.now(timezone.utc)

    def deactivate(self):
        self.is_active = False
        self.updated_at = datetime.now(timezone.utc)

    def update_services(self, service_ids: List[str]):
        self.service_ids = service_ids
        self.updated_at = datetime.now(timezone.utc)
