"""Alta, edicion y baja de usuarios del panel: dueno de la transaccion.

Hasta el 2026-09-17 (B3-06) ``UserRepository`` commiteaba por su cuenta y no
estaba en la lista de deuda declarada de CLAUDE.md. Ahora el repositorio solo
hace ``flush`` y este service, como ``appointments``, cierra la transaccion.

Ni en el alta ni en la edicion se traduce el ``IntegrityError``: sube al
handler global de ``main.py``, que responde 409 neutro (regla 20). Antes el
alta salia 400 "Ya existe un usuario con ese email" aunque la restriccion
violada fuera otra -el telefono unico de cliente por tienda-, o sea una causa
falsa (B3-12, 2026-09-18); la edicion se quedo con un 400 de mensaje neutro
pero codigo equivocado hasta AUD2-B3-10 (2026-09-20).
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
            # Misma decision que el alta (AUD2-B3-10): rollback y re-raise. El
            # 400 anterior tenia mensaje neutro pero codigo equivocado; chocar
            # con uq_users_client_phone_per_store o con uq_users_email_lower es
            # un conflicto, no un error de la solicitud, y el front no lo podia
            # distinguir de una validacion.
            await self.db.rollback()
            raise
        await self.db.refresh(updated)
        return updated

    async def soft_delete(self, user: User) -> None:
        await self.repo.soft_delete(user)
        await self.db.commit()
