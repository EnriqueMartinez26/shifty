from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import OperationalError

import modules.payments.jobs as jobs


class _Row:
    def __init__(self, value: Any) -> None:
        self.value = value

    def one_or_none(self) -> Any:
        return self.value

    def scalar_one_or_none(self) -> Any:
        return self.value


class _OutboxRow:
    def __init__(self, expires_at: datetime) -> None:
        self.id = "outbox-waitlist-retry"
        self.store_id = "store-1"
        self.event_type = jobs.EVENT_EMAIL_SEND
        self.payload = {
            "mail": "waitlist_offer",
            "args": {"email": "client@example.com", "details": {}},
            "waitlist_offer_guard": {
                "kind": "waitlist_offer",
                "entry_id": "entry-1",
                "staff_id": "staff-1",
                "starts_at": datetime(
                    2026, 11, 20, 13, tzinfo=timezone.utc
                ).isoformat(),
                "ends_at": datetime(
                    2026, 11, 20, 13, 30, tzinfo=timezone.utc
                ).isoformat(),
                "expires_at": expires_at.isoformat(),
            },
        }
        self.processed_at: datetime | None = None
        self.attempts = 0
        self.error: str | None = None
        self.delivery_status: str | None = "pending"
        self.next_attempt_at: datetime | None = None
        self.claimed_at: datetime | None = None
        self.is_active = True

    def register_failure(self, reason: str) -> None:
        self.attempts += 1
        self.error = reason[:1000]


@pytest.mark.parametrize(
    "failure", ["dbapi-abort", "soft-timeout"], ids=["sql-abortado", "soft-timeout"]
)
@pytest.mark.asyncio
async def test_guard_error_o_timeout_reabre_claim_para_el_siguiente_tick(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Rollback y recarga por ID recuperan el outbox antes de SMTP."""
    now = datetime.now(timezone.utc)
    starts_at = datetime(2026, 11, 20, 13, tzinfo=timezone.utc)
    ends_at = starts_at + timedelta(minutes=30)
    expires_at = now + timedelta(minutes=5)
    fila = _OutboxRow(expires_at)

    class _DB:
        aborted = False
        needs_rollback = False
        execute_calls = 0

        async def execute(self, _statement: Any) -> _Row:
            self.execute_calls += 1
            if self.aborted:
                raise AssertionError("SELECT intentado antes del rollback")
            if self.execute_calls == 1:
                self.needs_rollback = True
                if failure == "dbapi-abort":
                    self.aborted = True
                    raise OperationalError(
                        "SELECT waitlist_entries",
                        {},
                        RuntimeError("current transaction is aborted"),
                    )
                raise SoftTimeLimitExceeded()
            if self.execute_calls == 2:
                return _Row(fila)
            if self.execute_calls == 3:
                return _Row(
                    (True, "offered", "staff-1", starts_at, ends_at, expires_at)
                )
            raise AssertionError("unexpected SELECT")

    db = _DB()
    claims = 0
    sent: list[str] = []
    rollback_calls = 0
    commit_calls = 0
    rls_calls = 0

    async def claim(_db: Any, *, store_id: str | None = None) -> Any:
        nonlocal claims
        claims += 1
        now = datetime.now(timezone.utc)
        if (
            fila.processed_at is None
            and fila.delivery_status in {None, "pending"}
            and (fila.next_attempt_at is None or fila.next_attempt_at <= now)
        ):
            fila.delivery_status = "claimed"
            fila.claimed_at = now
            fila.next_attempt_at = None
            fila.processed_at = now
            return fila
        return None

    async def rollback(_db: Any) -> None:
        nonlocal rollback_calls
        rollback_calls += 1
        assert db.needs_rollback
        db.aborted = False
        db.needs_rollback = False

    async def commit(_db: Any) -> None:
        nonlocal commit_calls
        commit_calls += 1
        assert not db.aborted and not db.needs_rollback

    async def apply_context(_db: Any) -> None:
        nonlocal rls_calls
        rls_calls += 1
        assert not db.aborted and not db.needs_rollback

    async def send(row: Any, _smtp: Any) -> None:
        sent.append(row.id)

    class _SMTP:
        last_budget_decision: str | None = None
        last_delivery_retryable = False

    smtp = _SMTP()

    @asynccontextmanager
    async def smtp_session() -> AsyncIterator[_SMTP]:
        yield smtp

    monkeypatch.setattr(jobs, "_claim_next_email", claim)
    monkeypatch.setattr(jobs, "_send_one_pending_email", send)
    monkeypatch.setattr(jobs, "_apply_tenant_context", apply_context)
    monkeypatch.setattr(jobs, "smtp_session", smtp_session)
    monkeypatch.setattr("modules.payments.jobs.AsyncSession.rollback", rollback)
    monkeypatch.setattr("modules.payments.jobs.AsyncSession.commit", commit)

    if failure == "soft-timeout":
        with pytest.raises(SoftTimeLimitExceeded):
            await jobs._dispatch_pending_emails(db)  # type: ignore[arg-type]
    else:
        await jobs._dispatch_pending_emails(db)  # type: ignore[arg-type]

    assert rollback_calls == 1
    assert rls_calls == 2  # Antes del SELECT y reaplicado tras el rollback.
    assert fila.processed_at is None
    assert fila.attempts == 0
    assert fila.error == (
        "waitlist_offer_validation_failed" if failure == "dbapi-abort" else None
    )
    assert sent == []

    # El mismo row vuelve a ser seleccionable; la guarda ya lee y el mail sale.
    fila.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await jobs._dispatch_pending_emails(db)  # type: ignore[arg-type]

    assert claims == (4 if failure == "dbapi-abort" else 3)
    assert commit_calls == 3
    assert fila.processed_at is not None
    assert fila.attempts == 0
    assert sent == [fila.id]


@pytest.mark.asyncio
async def test_guard_ausente_terminaliza_sin_enviar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fila = _OutboxRow(datetime.now(timezone.utc) + timedelta(minutes=5))
    fila.payload.pop("waitlist_offer_guard")
    claims = 0
    commits = 0

    async def claim(_db: Any, *, store_id: str | None = None) -> Any:
        nonlocal claims
        claims += 1
        if fila.processed_at is None:
            fila.delivery_status = "claimed"
            fila.claimed_at = datetime.now(timezone.utc)
            fila.processed_at = datetime.now(timezone.utc)
            return fila
        return None

    async def apply_context(_db: Any) -> None:
        return None

    async def commit(_db: Any) -> None:
        nonlocal commits
        commits += 1

    async def send(_row: Any, _smtp: Any) -> None:
        raise AssertionError("an invalid offer guard must prevent SMTP")

    class _SMTP:
        last_budget_decision: str | None = None
        last_delivery_retryable = False

    @asynccontextmanager
    async def smtp_session() -> AsyncIterator[_SMTP]:
        yield _SMTP()

    monkeypatch.setattr(jobs, "_claim_next_email", claim)
    monkeypatch.setattr(jobs, "_send_one_pending_email", send)
    monkeypatch.setattr(jobs, "_apply_tenant_context", apply_context)
    monkeypatch.setattr(jobs, "smtp_session", smtp_session)
    monkeypatch.setattr("modules.payments.jobs.AsyncSession.commit", commit)

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]

    assert claims == 2
    assert commits == 1
    assert fila.processed_at is not None
    assert fila.error == "waitlist_offer_invalid_guard"
    assert fila.attempts == 0
