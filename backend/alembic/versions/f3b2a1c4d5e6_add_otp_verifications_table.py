"""add_otp_verifications_table

Revision ID: f3b2a1c4d5e6
Revises: e8a1b3c5d7f9
Create Date: 2026-05-28 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3b2a1c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e8a1b3c5d7f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "otp_verifications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("store_id", sa.String(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column(
            "channel", sa.String(length=20), nullable=False, server_default="whatsapp"
        ),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_otp_verifications_store_id", "otp_verifications", ["store_id"])
    op.create_index("ix_otp_verifications_phone", "otp_verifications", ["phone"])
    op.create_index(
        "ix_otp_verifications_code_hash", "otp_verifications", ["code_hash"]
    )
    op.create_index(
        "ix_otp_verifications_expires_at", "otp_verifications", ["expires_at"]
    )

    op.execute("ALTER TABLE otp_verifications ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE otp_verifications FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY otp_verifications_rls_policy ON otp_verifications
        USING (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)
        )
        WITH CHECK (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)
        );
        """
    )


def downgrade() -> None:
    op.drop_table("otp_verifications")
