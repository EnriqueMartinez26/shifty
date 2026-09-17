"""Alta, edicion y baja de usuarios del panel: dueno de la transaccion.

Hasta el 2026-09-17 (B3-06) ``UserRepository`` commiteaba por su cuenta y no
estaba en la lista de deuda declarada de CLAUDE.md. Ahora el repositorio solo
hace ``flush`` y este service, como ``appointments``, cierra la transaccion.

La traduccion de ``IntegrityError`` a ``ValueError`` se mueve tal cual desde el
repositorio: el contrato HTTP (400 con el mismo mensaje) no cambia aca; si
conviene dejar subir la ``IntegrityError`` al 409 neutro es la pregunta abierta
de B3-12, que este movimiento no decide.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User
from modules.users.repository import UserRepository


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = UserRepository(db)

    async def create(self, data: dict[str, Any], store_id: str | None) -> User:
        try:
            user = await self.repo.create(data, store_id)
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Ya existe un usuario con ese email")
        await self.db.refresh(user)
        return user

    async def update(self, user: User, data: dict[str, Any]) -> User:
        try:
            updated = await self.repo.update(user, data)
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("No se pudo actualizar el usuario")
        await self.db.refresh(updated)
        return updated

    async def soft_delete(self, user: User) -> None:
        await self.repo.soft_delete(user)
        await self.db.commit()
