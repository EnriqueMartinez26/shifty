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


def store_scope_for(user: User) -> str:
    """Tienda que acota TODAS las consultas de reportes y panel de este usuario.

    Es la capa de defensa en profundidad de CLAUDE.md §2: el predicado
    ``store_id`` viaja en la query aunque la politica RLS falle (en SQLite ni
    siquiera existe). Tambien para el superadmin (B5-02): la politica RLS se
    abre con ``app.is_global_admin`` y antes esto devolvia ``None``, asi que
    ``/reports`` y ``/dashboard`` le sumaban la plata, la deuda y los turnos de
    todas las tiendas. Decision: no hay consolidado (CLAUDE.md §1, espera el ok
    explicito del dueno); el superadmin ve su propia tienda. Nunca ``None``:
    no hay forma de pedir "sin filtro" desde aca.
    """
    return str(user.store_id)


def require_roles(user: User, allowed_roles: Iterable[str], detail: str) -> None:
    if not has_any_role(user, allowed_roles):
        raise AppException(
            message=detail,
            http_status=status.HTTP_403_FORBIDDEN,
            error_code="PERMISSION_DENIED",
        )
