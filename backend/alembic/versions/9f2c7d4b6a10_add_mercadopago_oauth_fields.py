"""add_mercadopago_oauth_fields

Revision ID: 9f2c7d4b6a10
Revises: b7c8d9e0f1a2
Create Date: 2026-06-08 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "9f2c7d4b6a10"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE payment_gateway_configs ADD COLUMN IF NOT EXISTS encrypted_refresh_token TEXT"
    )
    op.execute(
        "ALTER TABLE payment_gateway_configs ADD COLUMN IF NOT EXISTS connection_mode VARCHAR(20) NOT NULL DEFAULT 'manual'"
    )
    op.execute(
        "ALTER TABLE payment_gateway_configs ADD COLUMN IF NOT EXISTS oauth_user_id VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE payment_gateway_configs ADD COLUMN IF NOT EXISTS oauth_scope VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE payment_gateway_configs ADD COLUMN IF NOT EXISTS oauth_connected_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_appointments_expires_at ON appointments (expires_at)"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_payments_store_appointment'
            ) THEN
                ALTER TABLE payments
                ADD CONSTRAINT uq_payments_store_appointment
                UNIQUE (store_id, appointment_id);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE payments DROP CONSTRAINT IF EXISTS uq_payments_store_appointment"
    )
    op.execute("DROP INDEX IF EXISTS ix_appointments_expires_at")
    op.execute(
        "ALTER TABLE payment_gateway_configs DROP COLUMN IF EXISTS oauth_connected_at"
    )
    op.execute("ALTER TABLE payment_gateway_configs DROP COLUMN IF EXISTS oauth_scope")
    op.execute(
        "ALTER TABLE payment_gateway_configs DROP COLUMN IF EXISTS oauth_user_id"
    )
    op.execute(
        "ALTER TABLE payment_gateway_configs DROP COLUMN IF EXISTS connection_mode"
    )
    op.execute(
        "ALTER TABLE payment_gateway_configs DROP COLUMN IF EXISTS encrypted_refresh_token"
    )
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS expires_at")
