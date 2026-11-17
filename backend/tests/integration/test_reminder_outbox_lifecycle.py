"""A queued reminder must still describe a live appointment when it is sent."""

from __future__ import annotations

from contextlib import asynccontextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.jobs as jobs
from modules.appointments.model import Appointment
from modules.payments.model import OutboxMessage


async def _appointment(
    session: AsyncSession,
    *,
    appointment_id: str,
    store_id: str,
    status: str,
    starts_at: datetime,
) -> Appointment:
    appointment = Appointment(
        id=appointment_id,
        service_id="reminder-lifecycle-service",
        staff_id="reminder-lifecycle-staff",
        store_id=store_id,
        client_id=None,
        client_name="Cliente de prueba",
        client_email="cliente@example.com",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        duration_minutes=30,
        price_amount=100,
        status=status,
    )
    session.add(appointment)
    await session.flush()
    return appointment


def _reminder_row(
    *, appointment: Appointment, store_id: str, starts_at: datetime
) -> OutboxMessage:
    return OutboxMessage(
        store_id=store_id,
        event_type=jobs.EVENT_EMAIL_SEND,
        payload={
            "mail": "reminder",
            "args": {
                "email": "cliente@example.com",
                "details": {
                    "public_id": appointment.public_id,
                    "stage": "24h",
                    "starts_at": starts_at.isoformat(),
                    "service": "Corte",
                },
            },
            "source_event": "appointment.reminder",
            "appointment_id": appointment.id,
            "logical_id": f"reminder:{appointment.id}:24h",
            "expires_at": starts_at.isoformat(),
        },
    )


@pytest.fixture
def email_dispatch_fakes(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    class FakeSmtp:
        last_budget_decision: str | None = None
        last_delivery_retryable = False

    @asynccontextmanager
    async def fake_smtp_session() -> AsyncIterator[FakeSmtp]:
        yield FakeSmtp()

    async def fake_send_reminder(
        *, email: str | None, details: dict[str, Any], smtp: Any = None
    ) -> dict[str, str]:
        sent.append({"email": email, "details": details})
        return {"status": "sent"}

    def fake_delivery_context(**_kwargs: Any) -> Any:
        return nullcontext()

    monkeypatch.setattr(jobs, "smtp_session", fake_smtp_session)
    monkeypatch.setattr(jobs, "notify_client_reminder", fake_send_reminder)
    monkeypatch.setattr(jobs, "mail_delivery_context", fake_delivery_context)
    return sent


async def _load_outbox_row(session: AsyncSession, row_id: str) -> OutboxMessage:
    return (
        await session.execute(
            select(OutboxMessage)
            .where(OutboxMessage.id == row_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_cancelled_appointment_reminder_is_terminalized_without_smtp(
    test_session: AsyncSession, email_dispatch_fakes: list[dict[str, Any]]
) -> None:
    starts_at = datetime.now(timezone.utc) + timedelta(days=2)
    appointment = await _appointment(
        test_session,
        appointment_id="cancelled-reminder-appointment",
        store_id="reminder-store-a",
        status="cancelled",
        starts_at=starts_at,
    )
    reminder = _reminder_row(
        appointment=appointment, store_id="reminder-store-a", starts_at=starts_at
    )
    test_session.add(reminder)
    await test_session.commit()

    await jobs.process_outbox_batch(test_session, incluir_vencimientos=False)

    row = await _load_outbox_row(test_session, reminder.id)
    assert email_dispatch_fakes == []
    assert row.delivery_status == "expired"
    assert row.processed_at is not None
    assert row.error == "reminder_appointment_stale"
    assert row.attempts == 0


@pytest.mark.asyncio
async def test_rescheduled_appointment_does_not_send_old_reminder(
    test_session: AsyncSession, email_dispatch_fakes: list[dict[str, Any]]
) -> None:
    old_starts_at = datetime.now(timezone.utc) + timedelta(days=2)
    replacement_starts_at = old_starts_at + timedelta(days=1)
    original = await _appointment(
        test_session,
        appointment_id="rescheduled-reminder-original",
        store_id="reminder-store-a",
        status="cancelled",
        starts_at=old_starts_at,
    )
    replacement = await _appointment(
        test_session,
        appointment_id="rescheduled-reminder-replacement",
        store_id="reminder-store-a",
        status="confirmed",
        starts_at=replacement_starts_at,
    )
    reminder = _reminder_row(
        appointment=original, store_id="reminder-store-a", starts_at=old_starts_at
    )
    test_session.add(reminder)
    await test_session.commit()

    await jobs.process_outbox_batch(test_session, incluir_vencimientos=False)

    row = await _load_outbox_row(test_session, reminder.id)
    assert email_dispatch_fakes == []
    assert row.delivery_status == "expired"
    assert row.processed_at is not None
    assert row.error == "reminder_appointment_stale"
    assert row.attempts == 0
    assert replacement.status == "confirmed"


@pytest.mark.asyncio
async def test_reminder_appointment_lookup_is_scoped_to_outbox_store(
    test_session: AsyncSession, email_dispatch_fakes: list[dict[str, Any]]
) -> None:
    starts_at = datetime.now(timezone.utc) + timedelta(days=2)
    appointment = await _appointment(
        test_session,
        appointment_id="cross-store-reminder-appointment",
        store_id="reminder-store-a",
        status="confirmed",
        starts_at=starts_at,
    )
    reminder = _reminder_row(
        appointment=appointment, store_id="reminder-store-b", starts_at=starts_at
    )
    test_session.add(reminder)
    await test_session.commit()

    await jobs.process_outbox_batch(test_session, incluir_vencimientos=False)

    row = await _load_outbox_row(test_session, reminder.id)
    assert email_dispatch_fakes == []
    assert row.delivery_status == "expired"
    assert row.processed_at is not None
    assert row.error == "reminder_appointment_stale"
    assert row.attempts == 0
