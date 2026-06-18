"""drop denormalized business snapshots

Revision ID: 9d1a7b2c3e4f
Revises: f6a1b2c3d4e5
Create Date: 2026-06-18 09:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d1a7b2c3e4f"
down_revision: Union[str, Sequence[str], None] = "f6a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_appointments_store_client_phone", table_name="appointments")
    op.drop_column("appointments", "client_phone")
    op.drop_column("appointments", "client_email")
    op.drop_column("appointments", "client_name")
    op.drop_column("staff", "service_ids")
    op.drop_column("users", "full_name")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "full_name", sa.String(length=255), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "staff",
        sa.Column("service_ids", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "client_name", sa.String(length=255), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "appointments",
        sa.Column("client_email", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("client_phone", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "ix_appointments_store_client_phone",
        "appointments",
        ["store_id", "client_phone"],
        unique=False,
    )
