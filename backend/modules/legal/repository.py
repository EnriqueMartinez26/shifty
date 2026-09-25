"""Consultas de las constancias legales: sin reglas de negocio."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.legal.model import MarketingOptOut, StoreTermsAcceptance
from modules.users.model import User, UserRole


class StoreTermsRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def add(self, acceptance: StoreTermsAcceptance) -> None:
        self.db.add(acceptance)

    async def latest(self, store_id: str) -> StoreTermsAcceptance | None:
        """La ultima aceptacion de la tienda (``ix_..._store_accepted``)."""
        return (
            await self.db.execute(
                select(StoreTermsAcceptance)
                .where(StoreTermsAcceptance.store_id == store_id)
                .order_by(
                    StoreTermsAcceptance.accepted_at.desc(),
                    StoreTermsAcceptance.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()

    async def has_version(self, store_id: str, terms_version: str) -> bool:
        return (
            await self.db.execute(
                select(StoreTermsAcceptance.id)
                .where(
                    StoreTermsAcceptance.store_id == store_id,
                    StoreTermsAcceptance.terms_version == terms_version,
                )
                .limit(1)
            )
        ).first() is not None


class MarketingOptOutRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def add(self, opt_out: MarketingOptOut) -> None:
        self.db.add(opt_out)

    async def exists(self, store_id: str, client_id: str) -> bool:
        return (
            await self.db.execute(
                select(MarketingOptOut.id)
                .where(
                    MarketingOptOut.store_id == store_id,
                    MarketingOptOut.client_id == client_id,
                )
                .limit(1)
            )
        ).first() is not None

    async def client_of_store(self, store_id: str, client_id: str) -> bool:
        """El id es un cliente de ESA tienda (nunca personal ni admins)."""
        return (
            await self.db.execute(
                select(User.id)
                .where(
                    User.id == client_id,
                    User.store_id == store_id,
                    User.role == UserRole.CLIENT.value,
                )
                .limit(1)
            )
        ).first() is not None


async def opted_out_clients(
    db: AsyncSession, pairs: set[tuple[str, str]]
) -> set[tuple[str, str]]:
    """Los ``(store_id, client_id)`` de ``pairs`` con baja, en una consulta
    (el lote del outbox: regla 12)."""
    if not pairs:
        return set()
    filas = await db.execute(
        select(MarketingOptOut.store_id, MarketingOptOut.client_id).where(
            MarketingOptOut.store_id.in_({s for s, _ in pairs}),
            MarketingOptOut.client_id.in_({c for _, c in pairs}),
        )
    )
    return {(s, c) for s, c in filas.all() if (s, c) in pairs}
