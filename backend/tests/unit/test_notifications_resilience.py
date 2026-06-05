import pytest

from core.config import settings
import modules.notifications.tasks as notification_tasks


@pytest.mark.asyncio
async def test_confirmation_enqueue_does_not_raise_when_smtp_fallback_fails(monkeypatch) -> None:
    monkeypatch.setattr(settings, "VERCEL_QUEUE_REGION", None)
    monkeypatch.setattr(settings, "VERCEL_QUEUE_CONFIRMATION_FALLBACK_SYNC", True)

    async def smtp_failure(*args, **kwargs) -> bool:
        return False

    monkeypatch.setattr(notification_tasks, "_send_email", smtp_failure)

    result = await notification_tasks.enqueue_confirmation_email(
        email="cliente@example.com",
        details={"public_id": "appt-1", "service": "Consulta", "staff": "Pro Demo"},
        vercel_oidc_token=None,
    )

    assert result["status"] == "failed"
    assert result["reason"] == "RuntimeError"


@pytest.mark.asyncio
async def test_confirmation_enqueue_does_not_raise_when_queue_publish_fails(monkeypatch) -> None:
    monkeypatch.setattr(settings, "VERCEL_QUEUE_REGION", "iad1")

    async def publish_failure(*args, **kwargs) -> None:
        raise RuntimeError("queue down")

    monkeypatch.setattr(notification_tasks, "publish_json_message", publish_failure)

    result = await notification_tasks.enqueue_confirmation_email(
        email="cliente@example.com",
        details={"public_id": "appt-2", "service": "Consulta", "staff": "Pro Demo"},
        vercel_oidc_token="test-token",
    )

    assert result["status"] == "failed"
    assert result["reason"] == "RuntimeError"
