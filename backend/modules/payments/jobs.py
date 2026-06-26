from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from modules.payments.model import OutboxMessage, WebhookInbox
from modules.payments.processing import apply_mercadopago_webhook_payload


async def process_outbox_batch(
    db: AsyncSession,
    *,
    limit: int = 100,
    store_id: str | None = None,
) -> dict[str, int]:
    filters: list[ColumnElement[bool]] = [
        OutboxMessage.processed_at.is_(None),
        OutboxMessage.is_active.is_(True),
    ]
    if store_id:
        filters.append(OutboxMessage.store_id == store_id)

    result = await db.execute(
        select(OutboxMessage)
        .where(*filters)
        .order_by(OutboxMessage.created_at.asc())
        .limit(limit)
    )
    messages = list(result.scalars().all())
    now = datetime.now(timezone.utc)
    processed = 0
    failed = 0

    for message in messages:
        try:
            message.processed_at = now
            message.error = None
            processed += 1
        except Exception as exc:
            message.error = str(exc)[:1000]
            failed += 1

    await db.commit()
    return {"processed": processed, "failed": failed, "inspected": len(messages)}


async def process_webhook_inbox_batch(
    db: AsyncSession,
    *,
    limit: int = 100,
    store_id: str | None = None,
) -> dict[str, int]:
    filters: list[ColumnElement[bool]] = [
        WebhookInbox.processed_at.is_(None),
        WebhookInbox.is_active.is_(True),
    ]
    if store_id:
        filters.append(WebhookInbox.store_id == store_id)

    result = await db.execute(
        select(WebhookInbox)
        .where(*filters)
        .order_by(WebhookInbox.created_at.asc())
        .limit(limit)
    )
    inbox_items = list(result.scalars().all())
    processed = 0
    failed = 0

    for inbox in inbox_items:
        try:
            if inbox.provider == "mercadopago" and inbox.store_id:
                await apply_mercadopago_webhook_payload(
                    db, store_id=inbox.store_id, payload=inbox.payload
                )
            inbox.mark_processed()
            processed += 1
        except Exception as exc:
            inbox.error = str(exc)[:1000]
            failed += 1

    await db.commit()
    return {"processed": processed, "failed": failed, "inspected": len(inbox_items)}
