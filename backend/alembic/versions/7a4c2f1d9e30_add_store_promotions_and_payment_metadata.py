"""add_store_promotions_and_payment_metadata

Revision ID: 7a4c2f1d9e30
Revises: 1c4d7e9f2a10
Create Date: 2026-06-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7a4c2f1d9e30"
down_revision: Union[str, Sequence[str], None] = "1c4d7e9f2a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    ]


def _enable_rls(table_name: str, store_column: str = "store_id") -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY {table_name}_rls_policy ON {table_name}
        USING (
            current_setting('app.is_global_admin', true) = 'true'
            OR {store_column} = current_setting('app.current_store_id', true)
        )
        WITH CHECK (
            current_setting('app.is_global_admin', true) = 'true'
            OR {store_column} = current_setting('app.current_store_id', true)
        );
        """
    )


def upgrade() -> None:
    op.add_column("payments", sa.Column("original_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("payments", sa.Column("discount_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("payments", sa.Column("promotion_code", sa.String(length=50), nullable=True))

    op.create_table(
        "store_promotions",
        *_base_columns(),
        sa.Column("store_id", sa.String(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("promotion_type", sa.String(length=20), nullable=False, server_default="percent"),
        sa.Column("value", sa.Numeric(12, 2), nullable=False),
        sa.Column("min_service_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("current_uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("store_id", "code", name="uq_store_promotions_store_code"),
        sa.CheckConstraint("promotion_type IN ('percent', 'fixed')", name="ck_store_promotions_type"),
        sa.CheckConstraint("value > 0", name="ck_store_promotions_value_positive"),
        sa.CheckConstraint("min_service_amount IS NULL OR min_service_amount >= 0", name="ck_store_promotions_min_amount_non_negative"),
        sa.CheckConstraint("max_uses IS NULL OR max_uses > 0", name="ck_store_promotions_max_uses_positive"),
        sa.CheckConstraint("current_uses >= 0", name="ck_store_promotions_current_uses_non_negative"),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_from < valid_until",
            name="ck_store_promotions_valid_window",
        ),
    )
    op.create_index("ix_store_promotions_store_id", "store_promotions", ["store_id"])
    op.create_index("ix_store_promotions_code", "store_promotions", ["code"])

    op.create_table(
        "promotion_redemptions",
        *_base_columns(),
        sa.Column("store_id", sa.String(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("promotion_id", sa.String(), sa.ForeignKey("store_promotions.id"), nullable=False),
        sa.Column("appointment_id", sa.String(), sa.ForeignKey("appointments.id"), nullable=False),
        sa.Column("client_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("title_snapshot", sa.String(length=120), nullable=False),
        sa.Column("promotion_type_snapshot", sa.String(length=20), nullable=False),
        sa.Column("value_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("base_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("final_amount", sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint("promotion_id", "appointment_id", name="uq_promotion_redemptions_promotion_appointment"),
        sa.CheckConstraint("promotion_type_snapshot IN ('percent', 'fixed')", name="ck_promotion_redemptions_type"),
        sa.CheckConstraint("base_amount >= 0", name="ck_promotion_redemptions_base_non_negative"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_promotion_redemptions_discount_non_negative"),
        sa.CheckConstraint("final_amount >= 0", name="ck_promotion_redemptions_final_non_negative"),
    )
    op.create_index("ix_promotion_redemptions_store_id", "promotion_redemptions", ["store_id"])
    op.create_index("ix_promotion_redemptions_promotion_id", "promotion_redemptions", ["promotion_id"])
    op.create_index("ix_promotion_redemptions_appointment_id", "promotion_redemptions", ["appointment_id"])
    op.create_index("ix_promotion_redemptions_client_id", "promotion_redemptions", ["client_id"])

    _enable_rls("store_promotions")
    _enable_rls("promotion_redemptions")


def downgrade() -> None:
    op.drop_table("promotion_redemptions")
    op.drop_table("store_promotions")
    op.drop_column("payments", "promotion_code")
    op.drop_column("payments", "discount_amount")
    op.drop_column("payments", "original_amount")
