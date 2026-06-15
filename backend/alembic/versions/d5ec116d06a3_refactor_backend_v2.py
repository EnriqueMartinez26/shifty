"""refactor_backend_v2

Revision ID: d5ec116d06a3
Revises: 82f93e683770
Create Date: 2026-05-15 16:45:19.430598

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d5ec116d06a3"
down_revision: Union[str, Sequence[str], None] = "82f93e683770"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop RLS Policies
    policies_to_drop = [
        ("staff_services", "staff_services_rls_policy"),
        ("appointments", "appointments_rls_policy"),
        ("schedules", "schedules_rls_policy"),
        ("staff", "staff_rls_policy"),
        ("users", "users_rls_policy"),
        ("services", "services_rls_policy"),
        ("stores", "stores_rls_policy"),
        ("budgets", "budgets_rls_policy"),
    ]
    for table, policy in policies_to_drop:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table};")

    # 2. Drop ALL constraints that might block type changes
    constraints_to_drop = [
        ("appointments", "appointments_staff_id_fkey"),
        ("appointments", "appointments_service_id_fkey"),
        ("appointments", "appointments_store_id_fkey"),
        ("appointments", "appointments_client_id_fkey"),
        ("staff", "staff_store_id_fkey"),
        ("staff", "staff_user_id_fkey"),
        ("users", "users_store_id_fkey"),
        ("schedules", "schedules_store_id_fkey"),
        ("schedules", "schedules_staff_id_fkey"),
        ("staff_services", "staff_services_staff_id_fkey"),
        ("staff_services", "staff_services_service_id_fkey"),
        ("staff_blocks", "staff_blocks_staff_id_fkey"),
        ("staff_blocks", "staff_blocks_store_id_fkey"),
        ("budgets", "budgets_store_id_fkey"),
        ("audit_logs", "audit_logs_actor_id_fkey"),
        ("services", "services_store_id_fkey"),
        ("store_schedules", "store_schedules_store_id_fkey"),
    ]
    for table, constr in constraints_to_drop:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constr}")

    # 3. Alter column types (BigInt -> String) with USING
    # Foreign key columns FIRST
    op.execute(
        "ALTER TABLE staff ALTER COLUMN store_id TYPE VARCHAR USING store_id::text"
    )
    op.execute(
        "ALTER TABLE users ALTER COLUMN store_id TYPE VARCHAR USING store_id::text"
    )
    op.execute(
        "ALTER TABLE appointments ALTER COLUMN staff_id TYPE VARCHAR USING staff_id::text"
    )
    op.execute(
        "ALTER TABLE appointments ALTER COLUMN service_id TYPE VARCHAR USING service_id::text"
    )
    op.execute(
        "ALTER TABLE appointments ALTER COLUMN store_id TYPE VARCHAR USING store_id::text"
    )
    op.execute(
        "ALTER TABLE schedules ALTER COLUMN staff_id TYPE VARCHAR USING staff_id::text"
    )
    op.execute(
        "ALTER TABLE schedules ALTER COLUMN store_id TYPE VARCHAR USING store_id::text"
    )
    op.execute(
        "ALTER TABLE staff_services ALTER COLUMN staff_id TYPE VARCHAR USING staff_id::text"
    )
    op.execute(
        "ALTER TABLE staff_services ALTER COLUMN service_id TYPE VARCHAR USING service_id::text"
    )
    op.execute(
        "ALTER TABLE audit_logs ALTER COLUMN actor_id TYPE VARCHAR USING actor_id::text"
    )
    op.execute(
        "ALTER TABLE services ALTER COLUMN store_id TYPE VARCHAR USING store_id::text"
    )
    op.execute(
        "ALTER TABLE budgets ALTER COLUMN store_id TYPE VARCHAR USING store_id::text"
    )
    op.execute(
        "ALTER TABLE store_schedules ALTER COLUMN store_id TYPE VARCHAR USING store_id::text"
    )

    # Now Primary Keys
    for table in ["staff", "users", "appointments", "schedules", "stores", "services"]:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN id TYPE VARCHAR USING id::text")

    # 4. Apply other column changes
    op.add_column(
        "appointments",
        sa.Column(
            "duration_minutes", sa.Integer(), nullable=False, server_default="30"
        ),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "client_name",
            sa.String(length=255),
            nullable=False,
            server_default="Desconocido",
        ),
    )
    op.add_column(
        "appointments", sa.Column("client_email", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "appointments", sa.Column("client_phone", sa.String(length=50), nullable=True)
    )

    op.alter_column(
        "appointments",
        "starts_at",
        type_=sa.DateTime(),
        existing_type=postgresql.TIMESTAMP(timezone=True),
    )
    op.alter_column(
        "appointments",
        "created_at",
        type_=sa.DateTime(),
        existing_type=postgresql.TIMESTAMP(timezone=True),
    )
    op.alter_column(
        "appointments",
        "updated_at",
        type_=sa.DateTime(),
        existing_type=postgresql.TIMESTAMP(timezone=True),
    )

    op.add_column(
        "staff",
        sa.Column(
            "first_name", sa.String(length=100), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "staff",
        sa.Column(
            "last_name", sa.String(length=100), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "staff",
        sa.Column("email", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "staff",
        sa.Column("service_ids", sa.JSON(), nullable=False, server_default="[]"),
    )

    op.alter_column(
        "staff",
        "display_name",
        type_=sa.String(length=100),
        existing_type=sa.VARCHAR(length=255),
    )
    op.alter_column(
        "staff",
        "created_at",
        type_=sa.DateTime(),
        existing_type=postgresql.TIMESTAMP(timezone=True),
    )
    op.alter_column(
        "staff",
        "updated_at",
        type_=sa.DateTime(),
        existing_type=postgresql.TIMESTAMP(timezone=True),
    )

    op.add_column(
        "staff_services",
        sa.Column("rating", sa.Numeric(precision=2, scale=1), nullable=True),
    )

    op.add_column(
        "users",
        sa.Column(
            "full_name", sa.String(length=255), nullable=False, server_default=""
        ),
    )
    op.alter_column(
        "users",
        "created_at",
        type_=sa.DateTime(),
        existing_type=postgresql.TIMESTAMP(timezone=True),
    )
    op.alter_column(
        "users",
        "updated_at",
        type_=sa.DateTime(),
        existing_type=postgresql.TIMESTAMP(timezone=True),
    )

    # 5. Create new tables
    op.create_table(
        "appointment_blocks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("staff_id", sa.String(), nullable=False),
        sa.Column("store_id", sa.String(), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["staff.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_appointment_blocks_end_time"),
        "appointment_blocks",
        ["end_time"],
        unique=False,
    )
    op.create_index(
        op.f("ix_appointment_blocks_id"), "appointment_blocks", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_appointment_blocks_staff_id"),
        "appointment_blocks",
        ["staff_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_appointment_blocks_start_time"),
        "appointment_blocks",
        ["start_time"],
        unique=False,
    )
    op.create_index(
        op.f("ix_appointment_blocks_store_id"),
        "appointment_blocks",
        ["store_id"],
        unique=False,
    )

    # 6. Re-create RLS Policies
    op.execute("""
        CREATE POLICY stores_rls_policy ON stores
        USING (current_setting('app.is_global_admin', true) = 'true' OR id = current_setting('app.current_store_id', true))
        WITH CHECK (current_setting('app.is_global_admin', true) = 'true' OR id = current_setting('app.current_store_id', true));
    """)
    op.execute("""
        CREATE POLICY services_rls_policy ON services
        USING (current_setting('app.is_global_admin', true) = 'true' OR store_id = current_setting('app.current_store_id', true))
        WITH CHECK (current_setting('app.is_global_admin', true) = 'true' OR store_id = current_setting('app.current_store_id', true));
    """)
    op.execute("""
        CREATE POLICY users_rls_policy ON users
        USING (current_setting('app.is_global_admin', true) = 'true' OR store_id = current_setting('app.current_store_id', true))
        WITH CHECK (current_setting('app.is_global_admin', true) = 'true' OR store_id = current_setting('app.current_store_id', true));
    """)
    op.execute("""
        CREATE POLICY staff_rls_policy ON staff
        USING (current_setting('app.is_global_admin', true) = 'true' OR store_id = current_setting('app.current_store_id', true))
        WITH CHECK (current_setting('app.is_global_admin', true) = 'true' OR store_id = current_setting('app.current_store_id', true));
    """)
    op.execute("""
        CREATE POLICY schedules_rls_policy ON schedules
        USING (current_setting('app.is_global_admin', true) = 'true' OR store_id = current_setting('app.current_store_id', true))
        WITH CHECK (current_setting('app.is_global_admin', true) = 'true' OR store_id = current_setting('app.current_store_id', true));
    """)
    op.execute("""
        CREATE POLICY appointments_rls_policy ON appointments
        USING (current_setting('app.is_global_admin', true) = 'true' OR store_id = current_setting('app.current_store_id', true))
        WITH CHECK (current_setting('app.is_global_admin', true) = 'true' OR store_id = current_setting('app.current_store_id', true));
    """)
    op.execute("""
        CREATE POLICY staff_services_rls_policy ON staff_services
        USING (current_setting('app.is_global_admin', true) = 'true' OR EXISTS (
            SELECT 1 FROM staff s WHERE s.id = staff_services.staff_id AND s.store_id = current_setting('app.current_store_id', true)
        ))
        WITH CHECK (current_setting('app.is_global_admin', true) = 'true' OR EXISTS (
            SELECT 1 FROM staff s WHERE s.id = staff_services.staff_id AND s.store_id = current_setting('app.current_store_id', true)
        ));
    """)
    op.execute("""
        CREATE POLICY budgets_rls_policy ON budgets
        USING (current_setting('app.is_global_admin', true) = 'true' OR store_id = current_setting('app.current_store_id', true))
        WITH CHECK (current_setting('app.is_global_admin', true) = 'true' OR store_id = current_setting('app.current_store_id', true));
    """)

    # 7. Drop legacy tables/columns/indices
    op.execute("DROP TABLE IF EXISTS staff_blocks;")
    op.drop_column("appointments", "cancelled_at")
    op.drop_column("appointments", "is_active")
    op.drop_column("appointments", "public_id")
    op.drop_column("appointments", "client_id")
    op.drop_column("appointments", "completed_at")
    op.drop_column("appointments", "notes_staff")
    op.drop_column("staff", "public_id")
    op.drop_column("users", "public_id")
    op.drop_column("users", "phone")
    op.drop_column("users", "hashed_password")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
    op.drop_column("users", "password_reset_token_hash")
    op.drop_column("users", "password_reset_expires_at")
    op.drop_column("users", "is_global_admin")
    op.drop_column("schedules", "is_active")
    op.drop_column("schedules", "public_id")


def downgrade() -> None:
    pass
