"""PostgreSQL safety checks for SMTP outbox claims and worker restarts.

The delivery row is committed before SMTP. A second dispatcher must leave a
fresh claim to its active worker, while an abandoned claim is terminalized as
unknown because the provider may have accepted the message before the worker
stopped.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.payments.jobs as jobs
from core.database import _apply_tenant_context, set_tenant_context
from modules.payments.model import OutboxMessage
from tests.postgres.conftest import seed_store_and_admin

pytestmark = pytest.mark.postgres


async def _seed_email(
    sessions: async_sessionmaker[AsyncSession],
    *,
    slug: str,
    delivery_status: str,
    claimed_at: datetime | None = None,
) -> tuple[str, str]:
    store_id = await seed_store_and_admin(sessions, slug=slug, email=f"{slug}@demo.com")
    async with sessions() as db:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(db)
            row = OutboxMessage(
                store_id=store_id,
                event_type=jobs.EVENT_EMAIL_SEND,
                payload={
                    "mail": "confirmation",
                    "args": {"email": "cliente@example.com"},
                    "logical_id": f"email:{slug}",
                },
                delivery_status=delivery_status,
                claimed_at=claimed_at,
                processed_at=claimed_at,
            )
            db.add(row)
            await db.commit()
            return store_id, row.id
        finally:
            set_tenant_context(None, False)


async def _load_email(owner_engine: AsyncEngine, row_id: str) -> OutboxMessage:
    async with AsyncSession(owner_engine, expire_on_commit=False) as db:
        return (
            await db.execute(
                select(OutboxMessage)
                .where(OutboxMessage.id == row_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()


def _fake_smtp_session(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def fake_smtp_session() -> AsyncIterator[object]:
        yield object()

    monkeypatch.setattr(jobs, "smtp_session", fake_smtp_session)


async def _dispatch(sessions: async_sessionmaker[AsyncSession], store_id: str) -> None:
    async with sessions() as db:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(db)
            await jobs._dispatch_pending_emails(db, store_id=store_id)
        finally:
            set_tenant_context(None, False)


@pytest.mark.asyncio
async def test_fresh_claim_is_left_to_active_worker_and_sent_once(
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent dispatcher cannot steal a claim while SMTP is in flight."""
    store_id, row_id = await _seed_email(
        app_sessions, slug="email-claim-race", delivery_status="pending"
    )
    _fake_smtp_session(monkeypatch)
    smtp_started = asyncio.Event()
    finish_smtp = asyncio.Event()
    sends: list[str] = []

    async def slow_send(*, email: str, smtp: Any = None) -> dict[str, str]:
        sends.append(email)
        smtp_started.set()
        await finish_smtp.wait()
        return {"status": "sent"}

    monkeypatch.setattr(jobs, "send_confirmation_email", slow_send)

    first = asyncio.create_task(_dispatch(app_sessions, store_id))
    await asyncio.wait_for(smtp_started.wait(), timeout=5)
    await _dispatch(app_sessions, store_id)
    # Let the original worker finish only after the concurrent dispatcher has
    # returned, so a duplicate send cannot be hidden by ordering.
    finish_smtp.set()
    await asyncio.wait_for(first, timeout=5)

    row = await _load_email(owner_engine, row_id)
    assert sends == ["cliente@example.com"]
    assert row.delivery_status == "sent"
    assert row.processed_at is not None
    assert row.attempts == 0


@pytest.mark.asyncio
async def test_stale_claim_after_worker_restart_becomes_unknown_without_resend(
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An abandoned SMTP claim is ambiguous and therefore never retried."""
    claimed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    store_id, row_id = await _seed_email(
        app_sessions,
        slug="email-claim-restart",
        delivery_status="claimed",
        claimed_at=claimed_at,
    )
    _fake_smtp_session(monkeypatch)
    sends: list[str] = []

    async def send_if_called(*, email: str, smtp: Any = None) -> dict[str, str]:
        sends.append(email)
        return {"status": "sent"}

    monkeypatch.setattr(jobs, "send_confirmation_email", send_if_called)

    await _dispatch(app_sessions, store_id)

    row = await _load_email(owner_engine, row_id)
    assert sends == []
    assert row.delivery_status == "unknown"
    assert row.error == "stale_claim_unknown"
    assert row.processed_at is not None
    assert row.attempts == 0
