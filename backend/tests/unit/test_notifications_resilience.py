from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import modules.notifications.tasks as notification_tasks


@pytest.mark.asyncio
async def test_confirmation_enqueue_returns_failed_when_smtp_send_fails(
    monkeypatch,
) -> None:
    async def smtp_failure(*args, **kwargs) -> bool:
        return False

    monkeypatch.setattr(notification_tasks, "_send_email", smtp_failure)

    result = await notification_tasks.enqueue_confirmation_email(
        email="cliente@example.com",
        details={"public_id": "appt-1", "service": "Consulta", "staff": "Pro Demo"},
    )

    assert result == {"status": "failed", "reason": "RuntimeError"}


@pytest.mark.asyncio
async def test_process_due_appointment_reminders_counts_due_messages(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    appointment = SimpleNamespace(
        public_id="appt-2",
        starts_at=now + timedelta(hours=23),
    )
    service = SimpleNamespace(name="Consulta")
    staff = SimpleNamespace(display_name="Pro Demo")
    client = SimpleNamespace(email="cliente@example.com")
    store = SimpleNamespace(send_email_reminders=True)

    class _FakeRepo:
        def __init__(self, db) -> None:
            self.db = db

        async def get_upcoming_for_reminders(self, starts_after, starts_before):
            return [(appointment, service, staff, client, store)]

    class _FakeSessionFactory:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeRedis:
        async def set(self, *args, **kwargs):
            return True

        async def delete(self, *args, **kwargs):
            return 1

    async def fake_send_appointment_reminder(email: str, details: dict) -> dict:
        return {"status": "sent", "to": email}

    async def fake_get_redis() -> _FakeRedis:
        return _FakeRedis()

    monkeypatch.setattr(
        notification_tasks, "AsyncSessionFactory", lambda: _FakeSessionFactory()
    )
    monkeypatch.setattr(notification_tasks, "get_redis", fake_get_redis)
    monkeypatch.setattr(
        notification_tasks, "send_appointment_reminder", fake_send_appointment_reminder
    )
    monkeypatch.setattr(
        "modules.appointments.repository.AppointmentRepository",
        _FakeRepo,
    )

    result = await notification_tasks.process_due_appointment_reminders(
        now=now, lookahead_hours=48
    )

    assert result["status"] == "processed"
    assert result["published"] == 1
    assert result["skipped"] == 0
