"""enable rls policies

Revision ID: b3a2f8d1c5aa
Revises: 91d14f2a04fd
Create Date: 2026-04-11 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b3a2f8d1c5aa"
down_revision: Union[str, Sequence[str], None] = "91d14f2a04fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable RLS on tenant-scoped tables.
    op.execute("ALTER TABLE stores ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE services ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE staff ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE schedules ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE staff_services ENABLE ROW LEVEL SECURITY;")

    # Stores are visible only for the active tenant (or global admin).
    op.execute(
        """
        CREATE POLICY stores_rls_policy ON stores
        USING (
            current_setting('app.is_global_admin', true) = 'true'
            OR id = current_setting('app.current_store_id', true)::bigint
        )
        WITH CHECK (
            current_setting('app.is_global_admin', true) = 'true'
            OR id = current_setting('app.current_store_id', true)::bigint
        );
        """
    )

    op.execute(
        """
        CREATE POLICY services_rls_policy ON services
        USING (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)::bigint
        )
        WITH CHECK (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)::bigint
        );
        """
    )

    op.execute(
        """
        CREATE POLICY users_rls_policy ON users
        USING (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)::bigint
        )
        WITH CHECK (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)::bigint
        );
        """
    )

    op.execute(
        """
        CREATE POLICY staff_rls_policy ON staff
        USING (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)::bigint
        )
        WITH CHECK (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)::bigint
        );
        """
    )

    op.execute(
        """
        CREATE POLICY schedules_rls_policy ON schedules
        USING (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)::bigint
        )
        WITH CHECK (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)::bigint
        );
        """
    )

    op.execute(
        """
        CREATE POLICY appointments_rls_policy ON appointments
        USING (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)::bigint
        )
        WITH CHECK (
            current_setting('app.is_global_admin', true) = 'true'
            OR store_id = current_setting('app.current_store_id', true)::bigint
        );
        """
    )

    # Pivot table inherits tenant boundary from staff owner.
    op.execute(
        """
        CREATE POLICY staff_services_rls_policy ON staff_services
        USING (
            current_setting('app.is_global_admin', true) = 'true'
            OR EXISTS (
                SELECT 1
                FROM staff s
                WHERE s.id = staff_services.staff_id
                  AND s.store_id = current_setting('app.current_store_id', true)::bigint
            )
        )
        WITH CHECK (
            current_setting('app.is_global_admin', true) = 'true'
            OR EXISTS (
                SELECT 1
                FROM staff s
                WHERE s.id = staff_services.staff_id
                  AND s.store_id = current_setting('app.current_store_id', true)::bigint
            )
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS staff_services_rls_policy ON staff_services;")
    op.execute("DROP POLICY IF EXISTS appointments_rls_policy ON appointments;")
    op.execute("DROP POLICY IF EXISTS schedules_rls_policy ON schedules;")
    op.execute("DROP POLICY IF EXISTS staff_rls_policy ON staff;")
    op.execute("DROP POLICY IF EXISTS users_rls_policy ON users;")
    op.execute("DROP POLICY IF EXISTS services_rls_policy ON services;")
    op.execute("DROP POLICY IF EXISTS stores_rls_policy ON stores;")

    op.execute("ALTER TABLE staff_services DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE appointments DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE schedules DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE staff DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE services DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE stores DISABLE ROW LEVEL SECURITY;")
