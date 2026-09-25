"""Aceptacion de los terminos B2B por la tienda (L1, O-6 y 4.1; 2026-09-25).

El alta de la tienda la hace el superadmin y nadie aceptaba nada. El admin
de la tienda acepta la version vigente (``STORE_TERMS_VERSION``) y queda la
constancia (tienda, usuario, version, fecha, hash de la IP). No se bloquea el
panel: que hacer si falta la aceptacion lo decide el front. Dueno de la
transaccion (CLAUDE.md §2: commit solo en service).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import hash_ip
from modules.legal.model import StoreTermsAcceptance
from modules.legal.repository import StoreTermsRepository
from modules.users.model import User


@dataclass(frozen=True)
class StoreTermsStatus:
    current_version: str
    current_version_accepted: bool
    latest: StoreTermsAcceptance | None


class StoreTermsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = StoreTermsRepository(db)

    async def accept(self, *, actor: User, client_ip: str) -> StoreTermsAcceptance:
        """Registra la aceptacion de la version vigente por ``actor``.

        Aceptar dos veces la misma version deja dos filas: cada una es una
        constancia (quien y cuando) y no se pisan.
        """
        acceptance = StoreTermsAcceptance(
            store_id=actor.store_id,
            user_id=actor.id,
            terms_version=settings.STORE_TERMS_VERSION,
            accepted_at=datetime.now(timezone.utc),
            ip_hash=hash_ip(client_ip) if client_ip else None,
        )
        self.repo.add(acceptance)
        await self.db.commit()
        return acceptance

    async def status(self, store_id: str) -> StoreTermsStatus:
        vigente = settings.STORE_TERMS_VERSION
        return StoreTermsStatus(
            current_version=vigente,
            current_version_accepted=await self.repo.has_version(store_id, vigente),
            latest=await self.repo.latest(store_id),
        )
