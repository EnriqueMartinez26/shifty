from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.users.model import User


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict, store_id: int | None) -> User:
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
        store_id: int,
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

    async def get_by_public_id(self, public_id: str, store_id: int) -> User | None:
        result = await self.db.execute(
            select(User).where(
                User.id == public_id,
                User.store_id == store_id,
            )
        )
        return result.scalar_one_or_none()

    async def update(self, user: User, data: dict) -> User:
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
        await self.db.commit()
