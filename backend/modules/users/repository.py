from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.auth.service import revoke_sessions_for_user
from modules.users.model import User


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: dict[str, Any], store_id: str | None) -> User:
        if store_id is None:
            raise ValueError("No se pudo determinar el store del administrador")

        payload = data.copy()
        password = payload.pop("password")
        first_name = payload.get("first_name") or ""
        last_name = payload.get("last_name") or ""

        new_user = User(
            **payload,
            hashed_password=hash_password(password),
            store_id=store_id,
            full_name=f"{first_name} {last_name}".strip(),
        )
        self.db.add(new_user)

        try:
            await self.db.commit()
            await self.db.refresh(new_user)
            return new_user
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Ya existe un usuario con ese email")

    async def get_all(
        self,
        store_id: str,
        only_active: bool = True,
        email: str | None = None,
        role: str | None = None,
    ) -> list[User]:
        query = select(User).where(
            User.store_id == store_id,
        )
        if only_active:
            query = query.where(User.is_active.is_(True))
        if email:
            query = query.where(User.email == email)
        if role:
            query = query.where(User.role == role)

        query = query.order_by(User.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_public_id(self, public_id: str, store_id: str) -> User | None:
        result = await self.db.execute(
            select(User).where(
                User.id == public_id,
                User.store_id == store_id,
            )
        )
        return result.scalar_one_or_none()

    async def update(self, user: User, data: dict[str, Any]) -> User:
        payload = data.copy()
        password = payload.pop("password", None)

        for key, value in payload.items():
            if value is not None:
                setattr(user, key, value)

        if (
            payload.get("first_name") is not None
            or payload.get("last_name") is not None
        ):
            user.full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()

        if password:
            user.hashed_password = hash_password(password)

        # Una desactivacion, un cambio de rol o una clave impuesta por el admin
        # deben cortar las sesiones vivas: sin esto, los refresh tokens del
        # usuario siguen operando 30 dias con los permisos viejos.
        if (
            payload.get("is_active") is False
            or payload.get("role") is not None
            or password
        ):
            await revoke_sessions_for_user(self.db, user.id)

        try:
            await self.db.commit()
            await self.db.refresh(user)
            return user
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("No se pudo actualizar el usuario")

    async def soft_delete(self, user: User) -> None:
        user.is_active = False
        user.password_reset_token_hash = None
        user.password_reset_expires_at = None
        # La baja revoca las sesiones: si el usuario se reactiva mas adelante,
        # sus refresh tokens viejos no deben revivir con el.
        await revoke_sessions_for_user(self.db, user.id)
        await self.db.commit()
