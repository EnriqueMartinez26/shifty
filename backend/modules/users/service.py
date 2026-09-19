"""Alta, edicion y baja de usuarios del panel: dueno de la transaccion.

Hasta el 2026-09-17 (B3-06) ``UserRepository`` commiteaba por su cuenta y no
estaba en la lista de deuda declarada de CLAUDE.md. Ahora el repositorio solo
hace ``flush`` y este service, como ``appointments``, cierra la transaccion.

En el alta, un ``IntegrityError`` ya no se traduce: sube al handler global de
``main.py``, que responde 409 neutro (regla 20). Antes salia 400 "Ya existe un
usuario con ese email" aunque la restriccion violada fuera otra (el telefono
unico de cliente por tienda): una causa falsa (B3-12, 2026-09-18).
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
            # Rollback para dejar la sesion sana y re-raise: el handler global
            # responde 409 neutro sin nombrar la columna en conflicto.
            await self.db.rollback()
            raise
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
