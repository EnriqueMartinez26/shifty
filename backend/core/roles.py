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


def store_scope_for(user: User) -> str | None:
    """Tienda que acota TODAS las consultas de este usuario.

    Es la capa de defensa en profundidad de CLAUDE.md §2: el predicado
    ``store_id`` viaja en la query aunque la politica RLS falle (en SQLite ni
    siquiera existe). ``None`` solo para el superadmin, el mismo criterio con el
    que la politica RLS abre todo (``app.is_global_admin``); que tienda ve el
    superadmin en reportes y panel es una decision de producto aparte (B5-02).
    """
    if bool(getattr(user, "is_global_admin", False)):
        return None
    return str(user.store_id)


# Roles (valores de ``users.role``) que cada actor puede otorgar por /users/.
# Regla 16 de CLAUDE.md: el alta de admins es exclusiva del superadmin. Un admin
# de tienda da de alta y reasigna solo roles no-admin (B3-02, 2026-09-18).
GRANTABLE_BY_STORE_ADMIN = frozenset(
    {LEGACY_ROLE_STAFF, ROLE_RECEPTIONIST, ROLE_CLIENT}
)
GRANTABLE_BY_SUPER_ADMIN = GRANTABLE_BY_STORE_ADMIN | {LEGACY_ROLE_ADMIN}


def grantable_roles(actor: User) -> frozenset[str]:
    if bool(getattr(actor, "is_global_admin", False)):
        return GRANTABLE_BY_SUPER_ADMIN
    if has_any_role(actor, STORE_MANAGERS):
        return GRANTABLE_BY_STORE_ADMIN
    return frozenset()


def assert_can_grant_role(
    actor: User, requested: str | None, current: str | None = None
) -> None:
    """Rechaza (403) otorgar un rol que el actor no puede dar.

    ``current`` es el rol que el usuario ya tiene: reenviar el mismo rol no es
    otorgarlo (el formulario del panel manda el ``role`` actual en cada
    edicion), asi que un admin de tienda puede seguir editando a otro admin.
    """
    if requested is None:
        return
    pedido = str(getattr(requested, "value", requested))
    actual = str(getattr(current, "value", current)) if current is not None else None
    if pedido == actual or pedido in grantable_roles(actor):
        return
    raise AppException(
        message="Solo el soporte global puede otorgar ese rol",
        http_status=status.HTTP_403_FORBIDDEN,
        error_code="PERMISSION_DENIED",
    )


def require_roles(user: User, allowed_roles: Iterable[str], detail: str) -> None:
    if not has_any_role(user, allowed_roles):
        raise AppException(
            message=detail,
            http_status=status.HTTP_403_FORBIDDEN,
            error_code="PERMISSION_DENIED",
        )
