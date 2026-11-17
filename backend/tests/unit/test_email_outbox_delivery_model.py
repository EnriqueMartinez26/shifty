"""Contract for the durable SMTP delivery state stored on outbox rows."""

from __future__ import annotations

import pytest
from sqlalchemy import Table
from typing import cast

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
