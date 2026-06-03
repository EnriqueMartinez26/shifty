"""add_appointment_intake_answers

Revision ID: 1c4d7e9f2a10
Revises: f3b2a1c4d5e6
Create Date: 2026-06-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1c4d7e9f2a10"
down_revision: Union[str, Sequence[str], None] = "f3b2a1c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("appointments", sa.Column("intake_answers", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("appointments", "intake_answers")
