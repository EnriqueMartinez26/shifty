"""restore_runtime_contracts

Revision ID: f6a1b2c3d4e5
Revises: 6371c2cfaf0d
Create Date: 2026-05-18 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f6a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "6371c2cfaf0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_fk_if_missing(
    table: str, name: str, column: str, target: str, target_column: str = "id"
) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{name}'
            ) THEN
                ALTER TABLE {table}
                ADD CONSTRAINT {name}
                FOREIGN KEY ({column}) REFERENCES {target}({target_column});
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(255) NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_token_hash VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_password_reset_token_hash "
        "ON users (password_reset_token_hash)"
    )

    op.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS client_id VARCHAR")
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS ends_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS notes_staff TEXT")
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "UPDATE appointments "
        "SET ends_at = starts_at + make_interval(mins => duration_minutes) "
        "WHERE ends_at IS NULL AND duration_minutes IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS check_appointment_status_v2"
    )
    op.execute(
        "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS check_appointment_status_v3"
    )
    op.execute(
        "UPDATE appointments SET status = lower(status) WHERE status IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT check_appointment_status_v3 "
        "CHECK (status IN ('pending', 'confirmed', 'absent', 'completed', 'cancelled'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_appointments_client_id ON appointments (client_id)"
    )

    op.execute(
        "ALTER TABLE appointment_blocks ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true"
    )

    _add_fk_if_missing(
        "appointments", "appointments_client_id_fkey", "client_id", "users"
    )
    _add_fk_if_missing(
        "appointments", "appointments_service_id_fkey", "service_id", "services"
    )
    _add_fk_if_missing(
        "appointments", "appointments_staff_id_fkey", "staff_id", "staff"
    )
    _add_fk_if_missing(
        "appointments", "appointments_store_id_fkey", "store_id", "stores"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_store_id_fkey"
    )
    op.execute(
        "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_staff_id_fkey"
    )
    op.execute(
        "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_service_id_fkey"
    )
    op.execute(
        "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_client_id_fkey"
    )
    op.execute("DROP INDEX IF EXISTS ix_appointments_client_id")
    op.execute(
        "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS check_appointment_status_v3"
    )
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT check_appointment_status_v2 "
        "CHECK (status IN ('PENDING', 'CONFIRMED', 'ABSENT', 'COMPLETED', 'CANCELLED'))"
    )
    op.execute(
        "UPDATE appointments SET status = upper(status) WHERE status IS NOT NULL"
    )
    op.execute("ALTER TABLE appointment_blocks DROP COLUMN IF EXISTS is_active")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS completed_at")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS cancelled_at")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS notes_staff")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS client_id")
    op.execute("DROP INDEX IF EXISTS ix_users_password_reset_token_hash")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS password_reset_expires_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS password_reset_token_hash")
