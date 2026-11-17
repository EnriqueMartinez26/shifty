from __future__ import annotations

import smtplib
from datetime import datetime, timezone, tzinfo
from typing import Self, cast
from zoneinfo import ZoneInfo

import pytest

from core import mail_budget
from core.config import settings
from core.mail_budget import MailReservation, mail_delivery_context
from modules.notifications import tasks
from tests.redis_mail_budget_double import AtomicMailBudgetRedis


def _configure_reset(
    monkeypatch: pytest.MonkeyPatch, timezone_name: str, reset_hour: int
) -> ZoneInfo:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 100)
    monkeypatch.setattr(settings, "MAIL_BUDGET_TIMEZONE", timezone_name)
    monkeypatch.setattr(settings, "MAIL_BUDGET_RESET_HOUR", reset_hour)
    return ZoneInfo(timezone_name)


@pytest.mark.parametrize(
    ("local_now", "expected_utc"),
    [
        pytest.param(
            datetime(
                2026,
                11,
                13,
                5,
                59,
                59,
                tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
            ),
            datetime(2026, 11, 13, 9, tzinfo=timezone.utc),
            id="before-local-boundary",
        ),
        pytest.param(
            datetime(
                2026,
                11,
                13,
                6,
                tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
            ),
            datetime(2026, 11, 14, 9, tzinfo=timezone.utc),
            id="exact-boundary-advances-to-next-day",
        ),
        pytest.param(
            datetime(
                2026,
                11,
                13,
                6,
                0,
                1,
                tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
            ),
            datetime(2026, 11, 14, 9, tzinfo=timezone.utc),
            id="after-local-boundary",
        ),
    ],
)
def test_next_reset_uses_configured_local_boundary(
    monkeypatch: pytest.MonkeyPatch,
    local_now: datetime,
    expected_utc: datetime,
) -> None:
    _configure_reset(monkeypatch, "America/Argentina/Buenos_Aires", 6)

    assert mail_budget.next_mail_budget_reset_at(local_now) == expected_utc


@pytest.mark.parametrize(
    ("local_now", "expected_utc"),
    [
        pytest.param(
            datetime(2026, 3, 7, 6, tzinfo=ZoneInfo("America/New_York")),
            datetime(2026, 3, 8, 10, tzinfo=timezone.utc),
            id="spring-forward-short-day",
        ),
        pytest.param(
            datetime(2026, 10, 31, 6, tzinfo=ZoneInfo("America/New_York")),
            datetime(2026, 11, 1, 11, tzinfo=timezone.utc),
            id="fall-back-long-day",
        ),
    ],
)
def test_next_reset_tracks_dst_wall_clock_boundary(
    monkeypatch: pytest.MonkeyPatch,
    local_now: datetime,
    expected_utc: datetime,
) -> None:
    _configure_reset(monkeypatch, "America/New_York", 6)

    assert mail_budget.next_mail_budget_reset_at(local_now) == expected_utc


def test_next_reset_normalizes_nonexistent_dst_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zone = _configure_reset(monkeypatch, "America/New_York", 2)
    before_gap = datetime(2026, 3, 8, 1, 59, 59, tzinfo=zone)

    assert mail_budget.next_mail_budget_reset_at(before_gap) == datetime(
        2026, 3, 8, 7, tzinfo=timezone.utc
    )


class _FrozenDateTime(datetime):
    frozen = datetime(2026, 3, 8, 5, 30, tzinfo=ZoneInfo("America/New_York"))

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        if tz is None:
            return cast(Self, cls.frozen.replace(tzinfo=None))
        return cast(Self, cls.frozen.astimezone(tz))


@pytest.mark.asyncio
async def test_deferred_reservation_carries_next_reset_in_aware_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_reset(monkeypatch, "America/New_York", 6)
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 1)
    monkeypatch.setattr(settings, "MAIL_CRITICAL_RESERVE_PERCENT", 0)
    monkeypatch.setattr(settings, "MAIL_BUDGET_ALERT_PERCENT", 100)
    monkeypatch.setattr(mail_budget, "_report_threshold", lambda *_args: None)
    monkeypatch.setattr(mail_budget, "datetime", _FrozenDateTime)
    redis = AtomicMailBudgetRedis()

    async def get_redis() -> AtomicMailBudgetRedis:
        return redis

    monkeypatch.setattr(mail_budget, "get_redis", get_redis)
    admitted = await mail_budget.reserve_mail(priority="high", message_id="first")
    deferred = await mail_budget.reserve_mail(priority="high", message_id="second")

    assert admitted.decision == "admitted"
    assert admitted.retry_at is None
    assert deferred.decision == "deferred"
    assert deferred.retry_at == datetime(2026, 3, 8, 10, tzinfo=timezone.utc)
    assert deferred.retry_at.utcoffset() == timezone.utc.utcoffset(None)


@pytest.mark.asyncio
async def test_unavailable_reservation_has_no_provider_reset_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_reset(monkeypatch, "UTC", 0)
    monkeypatch.setattr(mail_budget, "_REDIS_RETRIES", 1)

    async def unavailable() -> None:
        raise OSError("redis unavailable")

    monkeypatch.setattr(mail_budget, "get_redis", unavailable)
    monkeypatch.setattr(mail_budget, "report_mail_failure", lambda **_kwargs: None)

    reservation = await mail_budget.reserve_mail(
        priority="critical", message_id="redis-unavailable"
    )

    assert reservation.decision == "unavailable"
    assert reservation.retry_at is None


def test_reservation_rejects_naive_retry_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        mail_budget.MailReservation(
            decision="deferred",
            window_id="test-window",
            message_key="key",
            attempt_token="token",
            priority="high",
            retry_at=datetime(2026, 11, 13, 9),
        )


@pytest.mark.asyncio
async def test_smtp_session_uses_deferred_retry_at_and_clears_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry_at = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)
    reservations = iter(
        [
            MailReservation(
                decision="deferred",
                window_id="test-window",
                message_key="deferred",
                attempt_token="deferred-token",
                priority="medium",
                retry_at=retry_at,
            ),
            MailReservation(
                decision="unavailable",
                window_id="test-window",
                message_key="unavailable",
                attempt_token="unavailable-token",
                priority="medium",
            ),
        ]
    )

    async def reserve(**_kwargs: object) -> MailReservation:
        return next(reservations)

    monkeypatch.setattr(tasks, "reserve_mail", reserve)
    session = tasks.SmtpSession()
    with mail_delivery_context(priority="medium", message_id="retry-at-test"):
        assert not await session.send("person@example.test", "Reminder", "body")
        assert session.last_budget_retry_at == retry_at
        assert session.last_delivery_attempted is False
        assert not await session.send("person@example.test", "Reminder", "body")

    assert session.last_budget_decision == "unavailable"
    assert session.last_budget_retry_at is None
    assert session.last_delivery_attempted is False
    assert session.last_delivery_ambiguous is False


@pytest.mark.asyncio
async def test_smtp_session_build_error_does_not_count_as_delivery_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = tasks.SmtpSession()

    def invalid_message(*_args: object, **_kwargs: object) -> None:
        raise ValueError("invalid mail message")

    monkeypatch.setattr(tasks, "_build_message", invalid_message)
    monkeypatch.setattr(tasks, "report_mail_failure", lambda **_kwargs: None)

    assert not await session.send("person@example.test", "Reminder", "body")

    assert session.last_budget_decision is None
    assert session.last_budget_retry_at is None
    assert session.last_delivery_attempted is False
    assert session.last_delivery_retryable is False
    assert session.last_delivery_ambiguous is False


@pytest.mark.asyncio
async def test_permanent_smtp_rejection_is_not_ambiguous_and_still_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reservation = MailReservation(
        decision="admitted",
        window_id="test-window",
        message_key="message",
        attempt_token="token",
        priority="medium",
        tracked=False,
    )
    finished: list[dict[str, object]] = []
    reports: list[dict[str, str]] = []

    class _RejectingSMTP:
        def send_message(self, _message: object) -> None:
            raise smtplib.SMTPResponseException(550, b"permanent rejection")

    async def reserve(**_kwargs: object) -> MailReservation:
        return reservation

    async def finish(_reservation: MailReservation, **result: object) -> None:
        finished.append(result)

    monkeypatch.setattr(tasks, "reserve_mail", reserve)
    monkeypatch.setattr(tasks, "finish_mail", finish)
    monkeypatch.setattr(
        tasks,
        "report_mail_failure",
        lambda **kwargs: reports.append(kwargs),
    )
    session = tasks.SmtpSession()
    rejecting_smtp = _RejectingSMTP()
    monkeypatch.setattr(session, "_connect", lambda: rejecting_smtp)

    with mail_delivery_context(
        priority="medium", message_id="permanent-rejection", retry_pre_data=True
    ):
        assert not await session.send("person@example.test", "Reminder", "body")

    assert session.last_delivery_retryable is False
    assert session.last_delivery_ambiguous is False
    assert session.last_delivery_attempted is True
    assert finished == [{"sent": False, "retryable": False}]
    assert reports == [
        {"component": "notifications", "error_type": "SMTPResponseException"}
    ]


@pytest.mark.asyncio
async def test_retryable_confirmation_failure_defers_failure_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reservation = MailReservation(
        decision="admitted",
        window_id="test-window",
        message_key="message",
        attempt_token="token",
        priority="high",
        tracked=False,
    )
    finished: list[dict[str, object]] = []
    reports: list[dict[str, str]] = []

    class _DisconnectedBeforeDataSMTP:
        def send_message(self, _message: object) -> None:
            raise ConnectionError("connection lost before DATA")

        def data(self, _message: bytes | str) -> tuple[int, bytes]:
            return 250, b"accepted"

        def close(self) -> None:
            return None

    async def reserve(**_kwargs: object) -> MailReservation:
        return reservation

    async def finish(_reservation: MailReservation, **result: object) -> None:
        finished.append(result)

    monkeypatch.setattr(tasks, "reserve_mail", reserve)
    monkeypatch.setattr(tasks, "finish_mail", finish)
    monkeypatch.setattr(
        tasks,
        "report_mail_failure",
        lambda **kwargs: reports.append(kwargs),
    )
    session = tasks.SmtpSession()
    monkeypatch.setattr(session, "_connect", _DisconnectedBeforeDataSMTP)

    with mail_delivery_context(
        priority="high", message_id="retryable-confirmation", retry_pre_data=True
    ):
        result = await tasks.send_confirmation_email(
            email="person@example.test",
            details={
                "public_id": "appointment-1",
                "service": "Consultation",
                "starts_at": "2026-11-20T12:00:00+00:00",
            },
            smtp=session,
        )

    assert result == {"status": "failed", "reason": "RuntimeError"}
    assert session.last_delivery_attempted is True
    assert session.last_delivery_retryable is True
    assert session.last_delivery_ambiguous is False
    assert finished == [{"sent": False, "retryable": True}]
    assert reports == []


@pytest.mark.asyncio
async def test_confirmation_template_error_clears_previous_retryable_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reports: list[dict[str, str]] = []
    session = tasks.SmtpSession()
    session.last_delivery_attempted = True
    session.last_delivery_retryable = True
    session.last_delivery_ambiguous = True

    async def fail_before_smtp(*_args: object, **_kwargs: object) -> dict[str, str]:
        raise ValueError("invalid confirmation details")

    monkeypatch.setattr(tasks, "send_appointment_confirmation", fail_before_smtp)
    monkeypatch.setattr(
        tasks,
        "report_mail_failure",
        lambda **kwargs: reports.append(kwargs),
    )

    result = await tasks.send_confirmation_email(
        email="person@example.test",
        details={"public_id": "appointment-1"},
        smtp=session,
    )

    assert result == {"status": "failed", "reason": "ValueError"}
    assert session.last_delivery_attempted is False
    assert session.last_delivery_retryable is False
    assert session.last_delivery_ambiguous is False
    assert reports == [{"component": "notifications", "error_type": "ValueError"}]
