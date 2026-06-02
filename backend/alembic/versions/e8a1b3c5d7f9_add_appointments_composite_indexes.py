"""add_appointments_composite_indexes

Revision ID: e8a1b3c5d7f9
Revises: d7f8a9b0c1d2
Create Date: 2026-05-26 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e8a1b3c5d7f9"
down_revision: Union[str, Sequence[str], None] = "d7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_appointments_store_staff_starts_at",
        "appointments",
        ["store_id", "staff_id", "starts_at"],
        unique=False,
    )
    op.create_index(
        "ix_appointments_store_status_starts_at",
        "appointments",
        ["store_id", "status", "starts_at"],
        unique=False,
    )
    op.create_index(
        "ix_appointments_store_client_phone",
        "appointments",
        ["store_id", "client_phone"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_appointments_store_client_phone", table_name="appointments")
    op.drop_index("ix_appointments_store_status_starts_at", table_name="appointments")
    op.drop_index("ix_appointments_store_staff_starts_at", table_name="appointments")
