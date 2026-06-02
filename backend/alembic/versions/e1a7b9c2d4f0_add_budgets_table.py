"""add budgets table

Revision ID: e1a7b9c2d4f0
Revises: c9f4b1a2d7e8
Create Date: 2026-04-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1a7b9c2d4f0"
down_revision: Union[str, Sequence[str], None] = "c9f4b1a2d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("store_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("improvement_description", sa.Text(), nullable=False),
        sa.Column("estimated_hours", sa.Numeric(10, 2), nullable=False),
        sa.Column("hourly_rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="ARS"),
        sa.Column("total_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=26), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_budgets_public_id"), "budgets", ["public_id"], unique=True)
    op.create_index(op.f("ix_budgets_store_id"), "budgets", ["store_id"], unique=False)

    op.execute("ALTER TABLE budgets ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY budgets_rls_policy ON budgets
        USING (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)::bigint
        )
        WITH CHECK (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)::bigint
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS budgets_rls_policy ON budgets")
    op.execute("ALTER TABLE budgets DISABLE ROW LEVEL SECURITY")

    op.drop_index(op.f("ix_budgets_store_id"), table_name="budgets")
    op.drop_index(op.f("ix_budgets_public_id"), table_name="budgets")
    op.drop_table("budgets")
