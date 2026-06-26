"""evolve_shifty_payments_auth_ledger

Revision ID: c2d4e6f8a901
Revises: b8e2f4a6c9d0
Create Date: 2026-05-25 00:00:00.000000

"""

from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2d4e6f8a901"
down_revision: Union[str, Sequence[str], None] = "b8e2f4a6c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
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
    op.add_column(
        "services", sa.Column("image_url", sa.String(length=500), nullable=True)
    )
    op.add_column(
        "services",
        sa.Column(
            "deposit_mode", sa.String(length=20), nullable=False, server_default="none"
        ),
    )
    op.add_column(
        "services",
        sa.Column(
            "deposit_type",
            sa.String(length=20),
            nullable=False,
            server_default="percent",
        ),
    )
    op.add_column(
        "services", sa.Column("deposit_amount", sa.Numeric(10, 2), nullable=True)
    )
    op.create_check_constraint(
        "ck_services_deposit_mode",
        "services",
        "deposit_mode IN ('none', 'optional', 'required')",
    )
    op.create_check_constraint(
        "ck_services_deposit_type",
        "services",
        "deposit_type IN ('percent', 'fixed', 'full')",
    )

    op.add_column(
        "appointments",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS check_appointment_status_v3;"
    )
    op.create_check_constraint(
        "check_appointment_status_v3",
        "appointments",
        "status IN ('pending', 'pending_payment', 'confirmed', 'absent', 'completed', 'cancelled', 'expired')",
    )
    op.execute(
        "ALTER TABLE store_schedules DROP CONSTRAINT IF EXISTS uq_store_day_schedule;"
    )
    op.create_index(
        "ix_store_schedules_store_day",
        "store_schedules",
        ["store_id", "day_of_week"],
        unique=False,
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("store_id", sa.String(), nullable=True),
        sa.Column("refresh_token_hash", sa.String(length=128), nullable=False),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("ip_address", sa.String(length=100), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_store_id", "auth_sessions", ["store_id"])
    op.create_index(
        "ix_auth_sessions_refresh_token_hash",
        "auth_sessions",
        ["refresh_token_hash"],
        unique=True,
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    op.create_table(
        "payment_gateway_configs",
        *_base_columns(),
        sa.Column("store_id", sa.String(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=50),
            nullable=False,
            server_default="mercadopago",
        ),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("public_key", sa.String(length=255), nullable=True),
        sa.Column("webhook_secret", sa.String(length=255), nullable=True),
        sa.UniqueConstraint(
            "store_id", "provider", name="uq_gateway_config_store_provider"
        ),
    )
    op.create_index(
        "ix_payment_gateway_configs_store_id", "payment_gateway_configs", ["store_id"]
    )

    op.create_table(
        "payments",
        *_base_columns(),
        sa.Column("store_id", sa.String(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id"),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.String(length=50),
            nullable=False,
            server_default="mercadopago",
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency", sa.String(length=10), nullable=False, server_default="ARS"
        ),
        sa.Column(
            "status", sa.String(length=50), nullable=False, server_default="pending"
        ),
        sa.Column("preference_id", sa.String(length=255), nullable=True),
        sa.Column("payment_link", sa.Text(), nullable=True),
        sa.Column("external_payment_id", sa.String(length=255), nullable=True),
        sa.Column("transaction_id", sa.String(length=255), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'refunded', 'manual_confirmed')",
            name="ck_payments_status",
        ),
    )
    op.create_index("ix_payments_store_id", "payments", ["store_id"])
    op.create_index("ix_payments_appointment_id", "payments", ["appointment_id"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index("ix_payments_preference_id", "payments", ["preference_id"])
    op.create_index(
        "ix_payments_external_payment_id", "payments", ["external_payment_id"]
    )

    op.create_table(
        "webhook_inbox",
        *_base_columns(),
        sa.Column("store_id", sa.String(), nullable=True),
        sa.Column(
            "provider",
            sa.String(length=50),
            nullable=False,
            server_default="mercadopago",
        ),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_webhook_inbox_store_id", "webhook_inbox", ["store_id"])
    op.create_index(
        "ix_webhook_inbox_event_id", "webhook_inbox", ["event_id"], unique=True
    )

    op.create_table(
        "outbox_messages",
        *_base_columns(),
        sa.Column("store_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_outbox_messages_store_id", "outbox_messages", ["store_id"])
    op.create_index("ix_outbox_messages_event_type", "outbox_messages", ["event_type"])

    op.create_table(
        "customer_ledger",
        *_base_columns(),
        sa.Column("store_id", sa.String(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("client_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id"),
            nullable=True,
        ),
        sa.Column("movement_type", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("balance_after", sa.Numeric(12, 2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "movement_type IN ('charge', 'payment', 'adjustment', 'refund')",
            name="ck_customer_ledger_type",
        ),
    )
    op.create_index(
        "ix_customer_ledger_store_client", "customer_ledger", ["store_id", "client_id"]
    )
    op.create_index(
        "ix_customer_ledger_appointment_id", "customer_ledger", ["appointment_id"]
    )

    for table in (
        "auth_sessions",
        "payment_gateway_configs",
        "payments",
        "webhook_inbox",
        "outbox_messages",
        "customer_ledger",
    ):
        _enable_rls(table)

    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ex_appointments_no_active_overlap'
            ) THEN
                ALTER TABLE appointments
                ADD CONSTRAINT ex_appointments_no_active_overlap
                EXCLUDE USING gist (
                    staff_id WITH =,
                    tstzrange(starts_at, ends_at, '[)') WITH &&
                )
                WHERE (status IN ('pending', 'pending_payment', 'confirmed'));
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS ex_appointments_no_active_overlap;"
    )
    for table in (
        "customer_ledger",
        "outbox_messages",
        "webhook_inbox",
        "payments",
        "payment_gateway_configs",
        "auth_sessions",
    ):
        op.drop_table(table)
    op.drop_index("ix_store_schedules_store_day", table_name="store_schedules")
    op.create_unique_constraint(
        "uq_store_day_schedule", "store_schedules", ["store_id", "day_of_week"]
    )
    op.execute(
        "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS check_appointment_status_v3;"
    )
    op.create_check_constraint(
        "check_appointment_status_v3",
        "appointments",
        "status IN ('pending', 'confirmed', 'absent', 'completed', 'cancelled')",
    )
    op.drop_column("appointments", "expires_at")
    op.drop_constraint("ck_services_deposit_type", "services", type_="check")
    op.drop_constraint("ck_services_deposit_mode", "services", type_="check")
    op.drop_column("services", "deposit_amount")
    op.drop_column("services", "deposit_type")
    op.drop_column("services", "deposit_mode")
    op.drop_column("services", "image_url")
