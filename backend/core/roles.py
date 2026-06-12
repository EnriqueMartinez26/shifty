from __future__ import annotations

from typing import Iterable

from fastapi import status

from core.exceptions import AppException
from modules.users.model import User


ROLE_SUPER_ADMIN = "super_admin"
ROLE_STORE_ADMIN = "store_admin"
ROLE_PROFESSIONAL = "professional"
ROLE_RECEPTIONIST = "receptionist"
ROLE_CLIENT = "client"

LEGACY_ROLE_ADMIN = "admin"
LEGACY_ROLE_STAFF = "staff"


def canonical_role(user: User | str, is_global_admin: bool | None = None) -> str:
    if isinstance(user, str):
        role = user
        global_admin = bool(is_global_admin)
    else:
        role = str(getattr(user, "role", "") or "")
        global_admin = bool(getattr(user, "is_global_admin", False))

    if global_admin:
        return ROLE_SUPER_ADMIN
    if role == LEGACY_ROLE_ADMIN:
        return ROLE_STORE_ADMIN
    if role == LEGACY_ROLE_STAFF:
        return ROLE_PROFESSIONAL
    return role


STORE_MANAGERS = {ROLE_SUPER_ADMIN, ROLE_STORE_ADMIN}
APPOINTMENT_MANAGERS = {
    ROLE_SUPER_ADMIN,
    ROLE_STORE_ADMIN,
    ROLE_PROFESSIONAL,
    ROLE_RECEPTIONIST,
}
FINANCIAL_OPERATORS = {
    ROLE_SUPER_ADMIN,
    ROLE_STORE_ADMIN,
    ROLE_PROFESSIONAL,
    ROLE_RECEPTIONIST,
}
FINANCIAL_ADMINS = {ROLE_SUPER_ADMIN, ROLE_STORE_ADMIN}
REPORT_VIEWERS = {ROLE_SUPER_ADMIN, ROLE_STORE_ADMIN, ROLE_PROFESSIONAL}
REPORT_EXPORTERS = {ROLE_SUPER_ADMIN, ROLE_STORE_ADMIN}


def has_any_role(user: User, allowed_roles: Iterable[str]) -> bool:
    return canonical_role(user) in set(allowed_roles)


def require_roles(user: User, allowed_roles: Iterable[str], detail: str) -> None:
    if not has_any_role(user, allowed_roles):
        raise AppException(message=detail, http_status=status.HTTP_403_FORBIDDEN, error_code="PERMISSION_DENIED")
