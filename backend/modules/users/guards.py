"""Guardas de baja de usuarios: la regla 14 en un solo lugar.

La guarda del "ultimo SuperAdmin" vivia solo dentro de
``UserAdminRepository.update_user`` (``PATCH /superadmin/users/{id}``), y el
bloqueo de la auto-baja solo en ``DELETE /users/{id}``: ``PATCH /users/{id}``
con ``is_active: false`` no tenia ninguna de las dos y en un solo request
dejaba la plataforma sin ningun SuperAdmin activo (AUD2-B3-01, 2026-09-19).
Ahora los tres caminos llaman aca.

``set_global_admin`` (``PATCH /superadmin/users/{id}/global-admin``) tenia una
CUARTA copia, con el conteo sin lock; tambien llama aca (AUD2-B3-12,
2026-09-20). Revocar el flag global deja la plataforma igual de vacia de
SuperAdmin que desactivar la cuenta, asi que las dos guardas son la misma.
"""

from __future__ import annotations

from http import HTTPStatus

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppException
from modules.users.model import User


def _denegar(message: str, error_code: str) -> AppException:
    return AppException(
        message=message,
        http_status=HTTPStatus.BAD_REQUEST,
        error_code=error_code,
    )


def active_global_admins_locked() -> Select[tuple[str]]:
    """Los SuperAdmin activos, tomados con ``SELECT ... FOR UPDATE``.

    Las guardas de la regla 14 eran "leer y despues actuar": contaban con un
    ``SELECT count(*)`` y escribian a continuacion, sin lock ni restriccion en
    la base que lo sostuviera. Con dos SuperAdmin activos y dos requests
    simultaneos (A revoca a B, B revoca a A) los dos leian 2, los dos pasaban y
    quedaban CERO (AUD2-B3-12). Tomando las filas candidatas ANTES de contar,
    el segundo request espera el lock y recien entonces cuenta, ya viendo el
    cambio del primero.

    Se eligio el lock de filas y no un advisory lock por tarea porque es el
    patron que el repo ya usa para verificar y actuar (``lock_staff_row``),
    acota el bloqueo a las pocas filas globales en vez de serializar toda baja
    de usuario de cualquier tienda, y no necesita liberacion explicita: muere
    con la transaccion. En SQLite ``FOR UPDATE`` se ignora, pero alli la
    escritura ya es unica; la rafaga real vive en ``tests/postgres/``.

    El ``ORDER BY`` no es cosmetico: fija el orden en que se toman las filas,
    asi que dos guardas simultaneas se serializan en vez de trabarse entre si.
    """
    return (
        select(User.id)
        .where(User.is_active.is_(True), User.is_global_admin.is_(True))
        .order_by(User.id)
        .with_for_update()
    )


async def _count_active_global_admins(db: AsyncSession) -> int:
    filas = (await db.execute(active_global_admins_locked())).scalars().all()
    return len(filas)


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

    activos = await _count_active_global_admins(db)

    if target.id == actor.id:
        raise _denegar(
            "No podés desactivar tu propio acceso SuperAdmin",
            "SELF_SUPERADMIN_DEACTIVATION_DENIED",
        )
    if activos <= 1:
        raise _denegar(
            "No se puede desactivar el último SuperAdmin activo",
            "LAST_SUPERADMIN_DEACTIVATION_DENIED",
        )


async def assert_global_admin_revocation_allowed(
    db: AsyncSession, actor: User, target: User
) -> None:
    """Regla 14 para ``is_global_admin: false``: mismo criterio, mismo lock.

    Se conservan las dos condiciones que ya aplicaba ``set_global_admin`` y su
    orden: primero la auto-revocacion (que no necesita mirar la base) y despues
    el conteo, que ahora toma el lock. Lo unico que cambia hacia afuera es que
    el 400 viaja con ``error_code`` en vez del generico, como el resto de las
    guardas de este modulo.

    Nota: el conteo se hace igual cuando el objetivo esta inactivo, tal como
    antes. Alinearlo con ``assert_deactivation_allowed`` -- que solo frena si el
    objetivo esta ACTIVO -- cambiaria un comportamiento observable del panel y
    no lo decide una auditoria.
    """
    if target.id == actor.id:
        raise _denegar(
            "No podés revocar tu propio acceso SuperAdmin",
            "SELF_SUPERADMIN_REVOCATION_DENIED",
        )
    if not target.is_global_admin:
        return
    if await _count_active_global_admins(db) <= 1:
        raise _denegar(
            "No se puede revocar el último SuperAdmin activo",
            "LAST_SUPERADMIN_REVOCATION_DENIED",
        )
