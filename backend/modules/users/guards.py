"""Guardas de baja de usuarios: la regla 14 en un solo lugar.

La guarda del "ultimo SuperAdmin" vivia solo dentro de
``UserAdminRepository.update_user`` (``PATCH /superadmin/users/{id}``), y el
bloqueo de la auto-baja solo en ``DELETE /users/{id}``: ``PATCH /users/{id}``
con ``is_active: false`` no tenia ninguna de las dos y en un solo request
dejaba la plataforma sin ningun SuperAdmin activo (AUD2-B3-01, 2026-09-19).
Ahora los tres caminos llaman aca.
"""

from __future__ import annotations

from http import HTTPStatus

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppException
from modules.users.model import User


def _denegar(message: str, error_code: str) -> AppException:
    return AppException(
        message=message,
        http_status=HTTPStatus.BAD_REQUEST,
        error_code=error_code,
    )


async def assert_deactivation_allowed(
    db: AsyncSession, actor: User, target: User, *, is_active: bool | None
) -> None:
    """Regla 14: no se desactiva al ultimo SuperAdmin activo ni uno a si mismo.

    ``is_active`` es lo que pide el request: ``False`` desactiva, ``None`` (no
    vino) y ``True`` no. Desactivar a quien ya esta inactivo no cambia nada y
    no se frena.

    Concurrencia: el conteo era "leer y despues actuar". Aca las filas
    candidatas -- los SuperAdmin activos, incluido el objetivo -- se toman con
    ``SELECT ... FOR UPDATE`` ANTES de contar, asi que dos bajas simultaneas se
    serializan: la segunda espera el lock y recien entonces cuenta, ya viendo
    la baja de la primera, y se rechaza. Se eligio el lock de filas y no un
    advisory lock por tarea porque es el patron que ya usa el repo para
    "verificar y actuar" (``lock_staff_row``), acota el bloqueo a las pocas
    filas globales en vez de serializar toda baja de usuario de cualquier
    tienda, y no necesita liberacion explicita: muere con la transaccion. En
    SQLite ``FOR UPDATE`` se ignora, pero alli la escritura ya es unica.
    """
    if is_active is not False or not target.is_active:
        return
    if not target.is_global_admin:
        return

    activos = (
        (
            await db.execute(
                select(User.id)
                .where(User.is_active.is_(True), User.is_global_admin.is_(True))
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )

    if target.id == actor.id:
        raise _denegar(
            "No podés desactivar tu propio acceso SuperAdmin",
            "SELF_SUPERADMIN_DEACTIVATION_DENIED",
        )
    if len(activos) <= 1:
        raise _denegar(
            "No se puede desactivar el último SuperAdmin activo",
            "LAST_SUPERADMIN_DEACTIVATION_DENIED",
        )
