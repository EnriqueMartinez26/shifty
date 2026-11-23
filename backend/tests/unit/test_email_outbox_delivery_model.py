"""Contract for the durable SMTP delivery state stored on outbox rows."""

from __future__ import annotations

import pytest
from sqlalchemy import Table
from typing import cast

import modules.notifications.tasks as notification_tasks
import modules.payments.model as payments_model
import modules.payments.jobs as payment_jobs
from modules.payments.model import EVENT_EMAIL_SEND, OutboxMessage


@pytest.mark.parametrize(
    "column_name",
    ("delivery_status", "next_attempt_at", "claimed_at"),
)
def test_smtp_delivery_state_columns_are_nullable(column_name: str) -> None:
    column = OutboxMessage.__table__.c[column_name]
    assert column.nullable is True


def test_smtp_delivery_has_its_own_ten_attempt_limit() -> None:
    assert getattr(payments_model, "OUTBOX_EMAIL_MAX_ATTEMPTS", None) == 10


def test_smtp_due_index_includes_legacy_pending_rows() -> None:
    table = cast(Table, OutboxMessage.__table__)
    index = next(
        index for index in table.indexes if index.name == "ix_outbox_email_due"
    )
    assert tuple(str(expression) for expression in index.expressions) == (
        "outbox_messages.event_type",
        "outbox_messages.is_active",
        "coalesce(next_attempt_at, created_at)",
        "outbox_messages.created_at",
    )
    assert str(index.dialect_options["postgresql"]["where"]) == ("processed_at IS NULL")


def test_smtp_claim_index_only_contains_active_claimed_rows() -> None:
    table = cast(Table, OutboxMessage.__table__)
    index = next(
        index for index in table.indexes if index.name == "ix_outbox_email_claimed"
    )
    assert tuple(column.name for column in index.columns) == ("claimed_at",)
    assert str(index.dialect_options["postgresql"]["where"]) == (
        "event_type = 'email.send' AND is_active IS TRUE AND "
        "delivery_status = 'claimed' AND claimed_at IS NOT NULL"
    )


def test_canonical_priority_wins_and_legacy_priority_is_validated_fallback() -> None:
    assert (
        payment_jobs._mail_priority_from_payload(
            {
                "mail": "encrypted_body",
                "priority": "critical",
                "args": {"priority": "low"},
            }
        )
        == "critical"
    )
    assert (
        payment_jobs._mail_priority_from_payload(
            {
                "mail": "encrypted_body",
                "priority": "critcal",
                "args": {"priority": "low"},
            }
        )
        == "low"
    )
    assert (
        payment_jobs._mail_priority_from_payload(
            {
                "mail": "encrypted_body",
                "priority": "critcal",
                "args": {"priority": "low-ish"},
            }
        )
        == "high"
    )


@pytest.mark.parametrize("status", ("sent", "failed", "unknown", "expired", "dropped"))
@pytest.mark.parametrize("guard_kind", ("otp", "password_reset"))
def test_terminal_auth_email_removes_encrypted_body_and_token_guard(
    status: str, guard_kind: str
) -> None:
    row = OutboxMessage(
        store_id="store-1",
        event_type=EVENT_EMAIL_SEND,
        payload={
            "mail": "encrypted_body",
            "priority": "critical",
            "args": {
                "to": "owner@example.com",
                "subject": "Authentication",
                "encrypted_body": "encrypted-secret",
            },
            "guard": {
                "kind": guard_kind,
                "otp_id": "otp-id",
                "token_hash": "reset-verifier",
            },
        },
    )

    payment_jobs._terminalize_email(row, status=status, reason="terminal")  # type: ignore[arg-type]

    assert row.delivery_status == status
    assert row.payload["args"] == {
        "to": "owner@example.com",
        "subject": "Authentication",
    }
    assert row.payload["guard"] == {"kind": guard_kind}


@pytest.mark.asyncio
async def test_invalid_encrypted_email_payload_is_observable_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sensitive-decryption-detail"
    failures: list[dict[str, str]] = []

    def fail_decrypt(_ciphertext: str) -> None:
        raise ValueError(secret)

    monkeypatch.setattr(notification_tasks, "decrypt_secret", fail_decrypt)
    monkeypatch.setattr(
        notification_tasks,
        "report_mail_failure",
        lambda **context: failures.append(context),
    )

    result = await notification_tasks.send_encrypted_outbox_email(
        smtp=cast(notification_tasks.SmtpSession, object()),
        to="owner@example.com",
        subject="Authentication",
        encrypted_body="corrupt-ciphertext",
    )

    assert result == {"status": "failed", "reason": "invalid_payload"}
    assert failures == [
        {
            "component": "notifications",
            "error_type": "OutboxEmailPayloadInvalid",
        }
    ]
    assert secret not in repr(result) + repr(failures)
