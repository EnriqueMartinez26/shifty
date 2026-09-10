"""lista de espera: tabla waitlist_entries con RLS forzada

Revision ID: f5b7c9d1e3a5
Revises: e4a6b8c0d2f4
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5b7c9d1e3a5"
down_revision: Union[str, Sequence[str], None] = "e4a6b8c0d2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "waitlist_entries"
_ABIERTA = "status IN ('waiting', 'offered')"


def upgrade() -> None:
    op.create_table(
        TABLA,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("store_id", sa.String(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("client_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_name", sa.String(length=100), nullable=False),
        sa.Column("client_phone", sa.String(length=30), nullable=False),
        sa.Column("client_email", sa.String(length=255), nullable=True),
        sa.Column(
            "service_id", sa.String(), sa.ForeignKey("services.id"), nullable=False
        ),
        sa.Column("staff_id", sa.String(), sa.ForeignKey("staff.id"), nullable=True),
        sa.Column("window_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="waiting"
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offer_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offered_staff_id", sa.String(), nullable=True),
        sa.Column("offered_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offered_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('waiting', 'offered', 'booked', 'cancelled', 'expired')",
            name="ck_waitlist_status",
        ),
        sa.CheckConstraint(
            "window_ends_at > window_starts_at", name="ck_waitlist_window"
        ),
    )
    for columna in (
        "store_id",
        "client_id",
        "client_phone",
        "service_id",
        "staff_id",
        "status",
        "offer_expires_at",
    ):
        op.create_index(f"ix_{TABLA}_{columna}", TABLA, [columna])
    op.create_index(
        "ix_waitlist_store_status_window",
        TABLA,
        ["store_id", "status", "window_starts_at"],
    )
    op.create_index(
        "uq_waitlist_open_entry",
        TABLA,
        ["store_id", "client_phone", "service_id", "window_starts_at"],
        unique=True,
        postgresql_where=sa.text(_ABIERTA),
        sqlite_where=sa.text(_ABIERTA),
    )

    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {TABLA} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLA} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {TABLA}_rls_policy ON {TABLA}
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


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP POLICY IF EXISTS {TABLA}_rls_policy ON {TABLA}")
    op.drop_table(TABLA)
