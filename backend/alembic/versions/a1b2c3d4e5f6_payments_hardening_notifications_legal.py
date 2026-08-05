"""payments hardening, in-app notifications and legal consent

Revision ID: a1b2c3d4e5f6
Revises: 9f2c7d4b6a10
Create Date: 2026-08-05

Agrega:
- ``webhook_inbox.attempts`` para reintentar webhooks que no se pudieron aplicar.
- ``stores.allow_manual_coordination`` y ``stores.deposit_policy`` para que cada
  tienda decida si acepta coordinar el pago por fuera y publique su politica.
- ``appointments.terms_accepted_at`` como respaldo del consentimiento del cliente.
- Tabla ``notifications`` para los avisos in-app del panel de la tienda.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "9f2c7d4b6a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "webhook_inbox",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "stores",
        sa.Column(
            "allow_manual_coordination",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column("stores", sa.Column("deposit_policy", sa.Text(), nullable=True))
    op.add_column(
        "appointments",
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("store_id", sa.String(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("appointment_id", sa.String(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_notifications_store_id", "notifications", ["store_id"])
    op.create_index("ix_notifications_type", "notifications", ["type"])
    op.create_index("ix_notifications_read_at", "notifications", ["read_at"])
    op.create_index(
        "ix_notifications_appointment_id", "notifications", ["appointment_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_appointment_id", table_name="notifications")
    op.drop_index("ix_notifications_read_at", table_name="notifications")
    op.drop_index("ix_notifications_type", table_name="notifications")
    op.drop_index("ix_notifications_store_id", table_name="notifications")
    op.drop_table("notifications")

    op.drop_column("appointments", "terms_accepted_at")
    op.drop_column("stores", "deposit_policy")
    op.drop_column("stores", "allow_manual_coordination")
    op.drop_column("webhook_inbox", "attempts")
