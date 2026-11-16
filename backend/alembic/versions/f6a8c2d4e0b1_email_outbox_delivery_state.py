"""add durable SMTP delivery state to outbox email rows

Revision ID: f6a8c2d4e0b1
Revises: e2b4d6f8a0c3
Create Date: 2026-11-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a8c2d4e0b1"
down_revision: Union[str, Sequence[str], None] = "e2b4d6f8a0c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDICES = {
    "ix_outbox_email_due": (
        "outbox_messages (next_attempt_at, created_at) "
        "WHERE event_type = 'email.send' AND processed_at IS NULL AND "
        "is_active IS TRUE AND (delivery_status IS NULL OR "
        "delivery_status = 'pending')"
    ),
    "ix_outbox_email_claimed": (
        "outbox_messages (claimed_at) "
        "WHERE event_type = 'email.send' AND is_active IS TRUE AND "
        "delivery_status = 'claimed' AND claimed_at IS NOT NULL"
    ),
}


def _create_indices() -> None:
    for name, definition in INDICES.items():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
        op.execute(f"CREATE INDEX CONCURRENTLY {name} ON {definition}")


def _drop_indices() -> None:
    for name in INDICES:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")


def upgrade() -> None:
    op.add_column(
        "outbox_messages",
        sa.Column("delivery_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    with op.get_context().autocommit_block():
        _create_indices()


def downgrade() -> None:
    with op.get_context().autocommit_block():
        _drop_indices()
    op.drop_column("outbox_messages", "claimed_at")
    op.drop_column("outbox_messages", "next_attempt_at")
    op.drop_column("outbox_messages", "delivery_status")
