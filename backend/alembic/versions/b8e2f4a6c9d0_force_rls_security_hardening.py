"""force_rls_security_hardening

Revision ID: b8e2f4a6c9d0
Revises: a7c9d1e2f3b4
Create Date: 2026-05-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b8e2f4a6c9d0"
down_revision: Union[str, Sequence[str], None] = "a7c9d1e2f3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RLS_TABLES = (
    "stores",
    "services",
    "users",
    "staff",
    "schedules",
    "store_schedules",
    "appointments",
    "appointment_blocks",
    "staff_services",
    "budgets",
    "plans",
    "saas_coupons",
    "store_subscriptions",
    "coupon_redemptions",
)


def _alter_rls(table_name: str, force: bool) -> None:
    mode = "FORCE" if force else "NO FORCE"
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = '{table_name}'
            ) THEN
                ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;
                ALTER TABLE {table_name} {mode} ROW LEVEL SECURITY;
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    for table_name in RLS_TABLES:
        _alter_rls(table_name, force=True)


def downgrade() -> None:
    for table_name in RLS_TABLES:
        _alter_rls(table_name, force=False)