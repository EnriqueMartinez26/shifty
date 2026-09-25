"""Consultas de la aceptacion de terminos B2B: sin reglas de negocio."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.legal.model import StoreTermsAcceptance


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
