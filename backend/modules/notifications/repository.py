"""Consultas de la campanita del panel. Sin reglas de negocio ni commits.

Cada consulta lleva ``Notification.store_id == store_id``: RLS es la garantia
y este filtro es la defensa en profundidad (CLAUDE.md §2). El commit es del
``NotificationService``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.notifications.model import Notification


class NotificationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_store(
        self, store_id: str, *, limit: int, unread_only: bool
    ) -> list[Notification]:
        filters = [
            Notification.store_id == store_id,
            Notification.is_active.is_(True),
        ]
        if unread_only:
            filters.append(Notification.read_at.is_(None))
        result = await self.db.execute(
            select(Notification)
            .where(*filters)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_unread(self, store_id: str) -> int:
        total = await self.db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.store_id == store_id,
                Notification.read_at.is_(None),
                Notification.is_active.is_(True),
            )
        )
        return int(total or 0)

    async def mark_read(self, notification_id: str, store_id: str) -> int | None:
        """Marca una notificacion de la tienda. ``None`` si no es de la tienda;
        si no, cuantas filas pasaron de no leida a leida (0 o 1)."""
        result = await self.db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.store_id == store_id,
            )
        )
        notification = result.scalar_one_or_none()
        if notification is None:
            return None
        updated = 0 if notification.read_at else 1
        notification.mark_read()
        return updated

    async def mark_all_read(self, store_id: str) -> int:
        """Marca todas las no leidas activas de la tienda. Devuelve cuantas.

        B4-06 (2026-09-18): un solo ``UPDATE ... WHERE``; antes se traian
        todas las no leidas como objetos ORM y se emitia un UPDATE por fila.
        ``read_at IS NULL`` conserva la semantica de ``Notification.mark_read``
        (no pisa un ``read_at`` previo).
        """
        result = await self.db.execute(
            update(Notification)
            .where(
                Notification.store_id == store_id,
                Notification.read_at.is_(None),
                Notification.is_active.is_(True),
            )
            .values(read_at=datetime.now(timezone.utc))
        )
        return int(getattr(result, "rowcount", 0) or 0)


__all__ = ["NotificationRepository"]
