from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

class UserRole(Enum):
    ADMIN = "ADMIN"
    STAFF = "STAFF"
    CLIENT = "CLIENT"

@dataclass
class User:
    """Domain entity representing a system user."""
    id: str
    email: str
    full_name: str
    role: UserRole
    store_id: str
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def deactivate(self):
        self.is_active = False
        self.updated_at = datetime.now(timezone.utc)

    def activate(self):
        self.is_active = True
        self.updated_at = datetime.now(timezone.utc)

    def change_role(self, new_role: UserRole):
        self.role = new_role
        self.updated_at = datetime.now(timezone.utc)
