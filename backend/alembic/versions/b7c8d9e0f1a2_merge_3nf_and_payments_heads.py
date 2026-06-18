"""merge 3nf and payments migration heads

Revision ID: b7c8d9e0f1a2
Revises: 7a4c2f1d9e30, 9d1a7b2c3e4f
Create Date: 2026-06-18 12:00:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "b7c8d9e0f1a2"
down_revision = ("7a4c2f1d9e30", "9d1a7b2c3e4f")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
