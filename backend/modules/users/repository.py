"""Consultas y escrituras de usuarios del panel. Sin commit: lo hace UserService."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from infrastructure.persistence.patch import apply_patch
from modules.auth.service import normalize_email, revoke_sessions_for_user
from modules.users.model import User


def _valor_de_rol(dato: object) -> str | None:
    """El rol como cadena, venga como ``UserRole`` o como ``str`` de la base.

    Misma lectura que ``core.roles``: la columna es ``String`` y el payload
    puede traer el enum, asi que la comparacion se hace sobre el valor.
    """
    return None if dato is None else str(getattr(dato, "value", dato))


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: dict[str, Any], store_id: str | None) -> User:
        """Alta sin commit (lo hace UserService)."""
        if store_id is None:
            raise ValueError("No se pudo determinar el store del administrador")

        payload = data.copy()
        password = payload.pop("password")
        first_name = payload.get("first_name") or ""
        last_name = payload.get("last_name") or ""
        # El login busca por igualdad sobre el email normalizado (F1-12): sin
        # normalizar, "X@a.com" y "x@a.com" convivian como dos filas y el login
        # de ambas pasaba a 500 (MultipleResultsFound). Con el email en
        # minusculas el duplicado choca con el indice unico y sale como 409
        # neutro; ck_users_email_lower rechaza en la base a cualquier camino
        # que se olvide de normalizar.
        payload["email"] = normalize_email(str(payload["email"]))

        new_user = User(
            **payload,
            hashed_password=hash_password(password),
            store_id=store_id,
            full_name=f"{first_name} {last_name}".strip(),
        )
        self.db.add(new_user)
        await self.db.flush()
        return new_user

    async def get_all(
        self,
        store_id: str,
        only_active: bool = True,
        email: str | None = None,
        role: str | None = None,
        limit: int = 200,
        offset: int = 0,
        include_global_admins: bool = False,
    ) -> list[User]:
        query = select(User).where(
            User.store_id == store_id,
        )
        if not include_global_admins:
            # Para el panel de una tienda la cuenta del superadmin no existe
            # aunque su store_id sea esta tienda (S-15, reglas 14 y 16).
            query = query.where(User.is_global_admin.is_(False))
        if only_active:
            query = query.where(User.is_active.is_(True))
        if email:
            query = query.where(User.email == email)
        if role:
            query = query.where(User.role == role)

        # Cota: la tabla crece con cada reserva publica (un User CLIENT por
        # cliente nuevo), asi que un listado sin techo escalaba mal. El default
        # de 200 preserva el contrato actual para tiendas chicas.
        query = query.order_by(User.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_public_id(
        self, public_id: str, store_id: str, *, include_global_admins: bool = False
    ) -> User | None:
        query = select(User).where(
            User.id == public_id,
            User.store_id == store_id,
        )
        if not include_global_admins:
            # Por defecto oculto: quien no lo pide explicitamente (el panel de
            # un admin de tienda, el fiado) no puede ver ni tocar la cuenta
            # global (S-15). Solo el superadmin la incluye.
            query = query.where(User.is_global_admin.is_(False))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def update(self, user: User, data: dict[str, Any]) -> User:
        """Edicion sin commit (lo hace UserService)."""
        payload = data.copy()
        password = payload.pop("password", None)
        # El rol vigente ANTES del patch: el formulario del panel reenvia el
        # ``role`` actual en cada edicion, asi que "vino un rol" no significa
        # "cambio el rol" (AUD2-B3-09).
        rol_pedido = _valor_de_rol(payload.get("role"))
        rol_anterior = _valor_de_rol(user.role)

        # El router manda solo lo que vino (``exclude_unset``) y ``apply_patch``
        # distingue "vino null" de "no vino": un null borra si la columna admite
        # NULL (telefono, nombre) y se ignora si es NOT NULL (rol, estado). Con
        # el patron viejo -- ``if value is not None`` -- no se podia borrar el
        # telefono de un usuario desde el panel (AUD2-B3-08).
        apply_patch(user, payload)

        if "first_name" in payload or "last_name" in payload:
            user.full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()

        if password:
            user.hashed_password = hash_password(password)

        # Una desactivacion, un cambio de rol o una clave impuesta por el admin
        # deben cortar las sesiones vivas: sin esto, los refresh tokens del
        # usuario siguen operando 30 dias con los permisos viejos (regla 15).
        # Reenviar el MISMO rol no es un cambio y no revoca nada: la misma
        # lectura que ya hacian ``assert_can_grant_role`` (con ``current``) y
        # ``assert_can_change_access`` en ``core/roles.py``.
        cambio_de_rol = rol_pedido is not None and rol_pedido != rol_anterior
        if payload.get("is_active") is False or cambio_de_rol or password:
            await revoke_sessions_for_user(self.db, user.id)

        await self.db.flush()
        return user

    async def soft_delete(self, user: User) -> None:
        """Baja sin commit (lo hace UserService)."""
        user.is_active = False
        user.password_reset_token_hash = None
        user.password_reset_expires_at = None
        # La baja revoca las sesiones: si el usuario se reactiva mas adelante,
        # sus refresh tokens viejos no deben revivir con el.
        await revoke_sessions_for_user(self.db, user.id)
        await self.db.flush()
