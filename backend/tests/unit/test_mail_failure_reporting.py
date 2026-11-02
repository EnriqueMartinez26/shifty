from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

import pytest
from structlog.testing import capture_logs

import modules.auth.service as auth_service
import modules.notifications.tasks as notification_tasks
from core import observability
from core.observability import OncePer

EMAIL = "persona.privada@example.com"


def test_report_mail_failure_redacts_exception_and_limits_repeated_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reports: list[tuple[BaseException, dict[str, Any]]] = []
    monkeypatch.setattr(observability, "_MAIL_FAILURE_ALERTS", OncePer(seconds=300))

    def capture_report(exc: BaseException, **context: Any) -> None:
        reports.append((exc, context))

    monkeypatch.setattr(
        observability,
        "report_exception",
        capture_report,
    )

    observability.report_mail_failure(
        component="notifications", error_type="SMTPRecipientsRefused"
    )
    observability.report_mail_failure(
        component="notifications", error_type="SMTPConnectError"
    )
    observability.report_mail_failure(
        component="auth", error_type="SMTPRecipientsRefused"
    )

    assert len(reports) == 2
    assert str(reports[0][0]) == "Mail delivery failed"
    assert reports[0][1] == {
        "component": "notifications",
        "error_type": "SMTPRecipientsRefused",
    }
    assert reports[1][1]["component"] == "auth"
    assert EMAIL not in repr(reports)


class _SmtpRechaza:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_SmtpRechaza":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def starttls(self, **_kwargs: Any) -> None:
        return None

    def login(self, *args: Any) -> None:
        return None

    def send_message(self, _message: Any) -> None:
        raise smtplib.SMTPRecipientsRefused(
            {EMAIL: (550, f"rejected <{EMAIL}>".encode())}
        )


def test_auth_email_sink_reports_smtp_failure_without_logging_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reports: list[dict[str, str]] = []
    monkeypatch.setattr(smtplib, "SMTP", _SmtpRechaza)
    monkeypatch.setattr(
        auth_service,
        "report_mail_failure",
        lambda **context: reports.append(context),
    )
    message = EmailMessage()
    message["To"] = EMAIL
    message.set_content("body")

    with capture_logs() as events:
        auth_service._send_email(message, event="password_reset_email_failed")

    assert reports == [{"component": "auth", "error_type": "SMTPRecipientsRefused"}]
    assert EMAIL not in repr(events)
    assert events[0]["event"] == "password_reset_email_failed"
    assert events[0]["error_type"] == "SMTPRecipientsRefused"


@pytest.mark.asyncio
async def test_reschedule_dispatch_failure_reports_without_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reports: list[dict[str, str]] = []

    async def fail_send(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError(f"SMTP rejected {EMAIL}")

    monkeypatch.setattr(notification_tasks, "_send_email", fail_send)
    monkeypatch.setattr(
        notification_tasks,
        "report_mail_failure",
        lambda **context: reports.append(context),
    )
    details = {"public_id": "appt-1", "service": "Corte", "staff": "Ana"}

    with capture_logs() as events:
        result = await notification_tasks.send_reschedule_email(
            email=EMAIL, details=details
        )

    assert result == {"status": "failed", "reason": "RuntimeError"}
    assert reports == [{"component": "notifications", "error_type": "RuntimeError"}]
    assert EMAIL not in repr(events)
