from infrastructure.persistence.models.user import UserModel as User
import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    STAFF = "staff"
    RECEPTIONIST = "receptionist"
    CLIENT = "client"
