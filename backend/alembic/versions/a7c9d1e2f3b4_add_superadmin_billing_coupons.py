"""add_superadmin_billing_coupons

Revision ID: a7c9d1e2f3b4
Revises: f6a1b2c3d4e5
Create Date: 2026-05-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7c9d1e2f3b4"
down_revision: Union[str, Sequence[str], None] = "f6a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    ]


def _create_global_only_policy(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table_name}_global_admin_policy ON {table_name}")
    op.execute(
        f"""
        CREATE POLICY {table_name}_global_admin_policy ON {table_name}
        USING (current_setting('app.is_global_admin', true) = 'true')
        WITH CHECK (current_setting('app.is_global_admin', true) = 'true')
        """
    )


def _create_store_policy(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table_name}_rls_policy ON {table_name}")
    op.execute(
        f"""
        CREATE POLICY {table_name}_rls_policy ON {table_name}
        USING (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)
        )
        WITH CHECK (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)
        )
        """
    )


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_global_admin BOOLEAN NOT NULL DEFAULT false")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_is_global_admin ON users (is_global_admin)")

    op.create_table(
        "plans",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="ARS"),
        sa.Column("billing_interval", sa.String(length=20), nullable=False, server_default="monthly"),
        sa.Column("max_staff", sa.Integer(), nullable=True),
        sa.Column("max_services", sa.Integer(), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("price >= 0", name="ck_plans_price_non_negative"),
    )
    op.create_index("ix_plans_name", "plans", ["name"], unique=True)

    op.create_table(
        "saas_coupons",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("coupon_type", sa.String(length=20), nullable=False),
        sa.Column("value", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("current_uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("one_time_per_store", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.String(), nullable=True),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("coupon_type IN ('percent', 'fixed')", name="ck_saas_coupons_type"),
        sa.CheckConstraint("value > 0", name="ck_saas_coupons_value_positive"),
        sa.CheckConstraint("current_uses >= 0", name="ck_saas_coupons_current_uses_non_negative"),
        sa.CheckConstraint("max_uses IS NULL OR max_uses > 0", name="ck_saas_coupons_max_uses_positive"),
        sa.CheckConstraint("valid_until IS NULL OR valid_from IS NULL OR valid_from < valid_until", name="ck_saas_coupons_valid_window"),
    )
    op.create_index("ix_saas_coupons_code", "saas_coupons", ["code"], unique=True)
    op.create_index("ix_saas_coupons_created_by_id", "saas_coupons", ["created_by_id"], unique=False)

    op.create_table(
        "store_subscriptions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("store_id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("base_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="ARS"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coupon_id", sa.String(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"]),
        sa.ForeignKeyConstraint(["coupon_id"], ["saas_coupons.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("base_amount >= 0", name="ck_store_subscriptions_base_non_negative"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_store_subscriptions_discount_non_negative"),
        sa.CheckConstraint("total_amount >= 0", name="ck_store_subscriptions_total_non_negative"),
        sa.CheckConstraint("discount_amount <= base_amount", name="ck_store_subscriptions_discount_lte_base"),
    )
    op.create_index("ix_store_subscriptions_store_id", "store_subscriptions", ["store_id"], unique=False)
    op.create_index("ix_store_subscriptions_plan_id", "store_subscriptions", ["plan_id"], unique=False)
    op.create_index("ix_store_subscriptions_coupon_id", "store_subscriptions", ["coupon_id"], unique=False)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_store_subscriptions_active_store "
        "ON store_subscriptions (store_id) WHERE is_active = true"
    )

    op.create_table(
        "coupon_redemptions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("coupon_id", sa.String(), nullable=False),
        sa.Column("store_id", sa.String(), nullable=False),
        sa.Column("subscription_id", sa.String(), nullable=True),
        sa.Column("redeemed_by_id", sa.String(), nullable=True),
        sa.Column("code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("coupon_type_snapshot", sa.String(length=20), nullable=False),
        sa.Column("value_snapshot", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("base_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("final_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["coupon_id"], ["saas_coupons.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.ForeignKeyConstraint(["subscription_id"], ["store_subscriptions.id"]),
        sa.ForeignKeyConstraint(["redeemed_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("base_amount >= 0", name="ck_coupon_redemptions_base_non_negative"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_coupon_redemptions_discount_non_negative"),
        sa.CheckConstraint("final_amount >= 0", name="ck_coupon_redemptions_final_non_negative"),
    )
    op.create_index("ix_coupon_redemptions_coupon_id", "coupon_redemptions", ["coupon_id"], unique=False)
    op.create_index("ix_coupon_redemptions_store_id", "coupon_redemptions", ["store_id"], unique=False)
    op.create_index("ix_coupon_redemptions_subscription_id", "coupon_redemptions", ["subscription_id"], unique=False)
    op.create_index("ix_coupon_redemptions_redeemed_by_id", "coupon_redemptions", ["redeemed_by_id"], unique=False)
    op.create_index("ix_coupon_redemptions_coupon_store", "coupon_redemptions", ["coupon_id", "store_id"], unique=False)

    _create_global_only_policy("plans")
    _create_global_only_policy("saas_coupons")
    _create_store_policy("store_subscriptions")
    _create_store_policy("coupon_redemptions")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS coupon_redemptions_rls_policy ON coupon_redemptions")
    op.execute("DROP POLICY IF EXISTS store_subscriptions_rls_policy ON store_subscriptions")
    op.execute("DROP POLICY IF EXISTS saas_coupons_global_admin_policy ON saas_coupons")
    op.execute("DROP POLICY IF EXISTS plans_global_admin_policy ON plans")

    op.drop_index("ix_coupon_redemptions_coupon_store", table_name="coupon_redemptions")
    op.drop_index("ix_coupon_redemptions_redeemed_by_id", table_name="coupon_redemptions")
    op.drop_index("ix_coupon_redemptions_subscription_id", table_name="coupon_redemptions")
    op.drop_index("ix_coupon_redemptions_store_id", table_name="coupon_redemptions")
    op.drop_index("ix_coupon_redemptions_coupon_id", table_name="coupon_redemptions")
    op.drop_table("coupon_redemptions")

    op.execute("DROP INDEX IF EXISTS uq_store_subscriptions_active_store")
    op.drop_index("ix_store_subscriptions_coupon_id", table_name="store_subscriptions")
    op.drop_index("ix_store_subscriptions_plan_id", table_name="store_subscriptions")
    op.drop_index("ix_store_subscriptions_store_id", table_name="store_subscriptions")
    op.drop_table("store_subscriptions")

    op.drop_index("ix_saas_coupons_created_by_id", table_name="saas_coupons")
    op.drop_index("ix_saas_coupons_code", table_name="saas_coupons")
    op.drop_table("saas_coupons")

    op.drop_index("ix_plans_name", table_name="plans")
    op.drop_table("plans")

    op.execute("DROP INDEX IF EXISTS ix_users_is_global_admin")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_global_admin")