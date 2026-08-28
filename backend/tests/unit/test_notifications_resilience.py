from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import modules.notifications.tasks as notification_tasks


@pytest.mark.asyncio
async def test_confirmation_enqueue_returns_failed_when_smtp_send_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def smtp_failure(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(notification_tasks, "_send_email", smtp_failure)

    result = await notification_tasks.enqueue_confirmation_email(
        email="cliente@example.com",
        details={"public_id": "appt-1", "service": "Consulta", "staff": "Pro Demo"},
    )

    assert result == {"status": "failed", "reason": "RuntimeError"}


@pytest.mark.asyncio
async def test_process_due_appointment_reminders_counts_due_messages(
    monkeypatch: pytest.MonkeyPatch,
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
        def __init__(self, db: Any) -> None:
            self.db = db

        async def get_upcoming_for_reminders(
            self, starts_after: datetime, starts_before: datetime
        ) -> list[tuple[Any, Any, Any, Any, Any]]:
            return [(appointment, service, staff, client, store)]

    class _FakeSessionFactory:
        async def __aenter__(self) -> SimpleNamespace:
            return SimpleNamespace()

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

    class _FakeRedis:
        async def set(self, *args: Any, **kwargs: Any) -> bool:
            return True

        async def delete(self, *args: Any, **kwargs: Any) -> int:
            return 1

    async def fake_notify_client_reminder(
        *, phone: str | None, email: str | None, details: dict[str, Any]
    ) -> dict[str, str]:
        # El recordatorio es multicanal: WhatsApp primero, mail como respaldo.
        return {"status": "sent", "channel": "whatsapp", "to": phone or email or ""}

    async def fake_get_redis() -> _FakeRedis:
        return _FakeRedis()

    monkeypatch.setattr(
        notification_tasks, "AsyncSessionFactory", lambda: _FakeSessionFactory()
    )
    monkeypatch.setattr(notification_tasks, "get_redis", fake_get_redis)
    monkeypatch.setattr(
        notification_tasks, "notify_client_reminder", fake_notify_client_reminder
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
