"""Campanita del panel: dueno de la transaccion (CLAUDE.md §2).

B4-05 (2026-09-18): el router commiteaba y armaba sus consultas. Ahora el
router solo traduce HTTP, este service commitea y ``NotificationRepository``
hace las consultas filtradas por tienda.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import ResourceNotFoundException
from modules.notifications.model import Notification
from modules.notifications.repository import NotificationRepository


@dataclass(frozen=True)
class MarkReadResult:
    updated: int
    unread_count: int


class NotificationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = NotificationRepository(db)

    async def list_for_store(
        self, store_id: str, *, limit: int, unread_only: bool
    ) -> tuple[list[Notification], int]:
        items = await self.repo.list_for_store(
            store_id, limit=limit, unread_only=unread_only
        )
        return items, await self.repo.count_unread(store_id)

    async def mark_read(self, notification_id: str, store_id: str) -> MarkReadResult:
        updated = await self.repo.mark_read(notification_id, store_id)
        if updated is None:
            raise ResourceNotFoundException(
                resource="Notificacion", identifier=notification_id
            )
        await self.db.commit()
        return MarkReadResult(
            updated=updated, unread_count=await self.repo.count_unread(store_id)
        )

    async def mark_all_read(self, store_id: str) -> MarkReadResult:
        updated = await self.repo.mark_all_read(store_id)
        await self.db.commit()
        return MarkReadResult(
            updated=updated, unread_count=await self.repo.count_unread(store_id)
        )


__all__ = ["MarkReadResult", "NotificationService"]
