"""add_store_feature_flags

Revision ID: d7f8a9b0c1d2
Revises: c2d4e6f8a901
Create Date: 2026-05-26 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "c2d4e6f8a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stores",
        sa.Column(
            "feature_flags",
            sa.JSON(),
            nullable=False,
            server_default=sa.text(
                "'{\"payments\": false, \"ledger\": false, \"advanced_reports\": false, \"new_calendar\": false}'"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("stores", "feature_flags")
