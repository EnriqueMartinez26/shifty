"""Contract for the durable SMTP delivery state stored on outbox rows."""

from __future__ import annotations

import pytest

import modules.payments.model as payments_model
from modules.payments.model import OutboxMessage


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
    index = next(
        index
        for index in OutboxMessage.__table__.indexes
        if index.name == "ix_outbox_email_due"
    )
    assert tuple(column.name for column in index.columns) == (
        "next_attempt_at",
        "created_at",
    )
    assert str(index.dialect_options["postgresql"]["where"]) == (
        "event_type = 'email.send' AND processed_at IS NULL AND "
        "is_active IS TRUE AND (delivery_status IS NULL OR "
        "delivery_status = 'pending')"
    )


def test_smtp_claim_index_only_contains_active_claimed_rows() -> None:
    index = next(
        index
        for index in OutboxMessage.__table__.indexes
        if index.name == "ix_outbox_email_claimed"
    )
    assert tuple(column.name for column in index.columns) == ("claimed_at",)
    assert str(index.dialect_options["postgresql"]["where"]) == (
        "event_type = 'email.send' AND is_active IS TRUE AND "
        "delivery_status = 'claimed' AND claimed_at IS NOT NULL"
    )
