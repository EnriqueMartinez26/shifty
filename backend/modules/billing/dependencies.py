"""Guarda de suscripcion suspendida.

Decision de producto (2026-09-10): una tienda suspendida deja de aparecer en
la vitrina publica y no puede escribir desde el panel; el login y la lectura
siguen para que el dueno vea el aviso y pueda pagar. El superadmin no queda
atrapado por la guarda: es quien reactiva la tienda.

Se aplica a nivel router (``dependencies=[Depends(block_writes_when_suspended)]``)
para que un endpoint de escritura nuevo quede cubierto sin acordarse de nada.
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.exceptions import AppException
from modules.auth.dependencies import get_optional_current_user
from modules.billing.service import store_is_suspended
from modules.users.model import User

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class SubscriptionSuspendedException(AppException):
    def __init__(self) -> None:
        super().__init__(
            message=(
                "Tu suscripcion esta suspendida: renovala para volver a operar. "
                "Podes seguir viendo tu informacion mientras tanto."
            ),
            http_status=HTTPStatus.PAYMENT_REQUIRED,
            error_code="SUBSCRIPTION_SUSPENDED",
        )


async def block_writes_when_suspended(
    request: Request,
    user: User | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Usuario OPCIONAL: estos routers tienen GET publicos (por ejemplo, servir
    # el logo de la tienda). Exigir autenticacion aca los rompia con 401.
    if request.method in SAFE_METHODS:
        return
    if user is None or user.is_global_admin or not user.store_id:
        return
    if await store_is_suspended(db, user.store_id):
        raise SubscriptionSuspendedException()
