from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from domain.entities.user import User, UserRole
from infrastructure.persistence.models.user import UserModel

class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_id(self, id: str) -> Optional[User]:
        stmt = select(UserModel).where(UserModel.id == id)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._map_to_entity(model) if model else None

    async def find_by_email(self, email: str) -> Optional[User]:
        stmt = select(UserModel).where(UserModel.email == email)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._map_to_entity(model) if model else None

    async def save(self, user: User) -> User:
        model = await self.session.get(UserModel, user.id)
        if not model:
            model = UserModel(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=user.role.value,
                store_id=user.store_id,
                is_active=user.is_active,
                created_at=user.created_at,
                updated_at=user.updated_at
            )
            self.session.add(model)
        else:
            model.full_name = user.full_name
            model.role = user.role.value
            model.is_active = user.is_active
            model.updated_at = user.updated_at
        
        await self.session.flush()
        return self._map_to_entity(model)

    def _map_to_entity(self, model: UserModel) -> User:
        return User(
            id=model.id,
            email=model.email,
            full_name=model.full_name,
            role=UserRole(model.role),
            store_id=model.store_id,
            is_active=model.is_active,
            created_at=model.created_at,
            updated_at=model.updated_at
        )
