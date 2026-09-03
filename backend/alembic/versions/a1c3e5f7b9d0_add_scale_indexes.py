"""add_scale_indexes

Indices para sostener carga a escala, detectados en la auditoria de rendimiento:
- appointments (store_id, starts_at): agenda diaria y reportes por rango que NO
  filtran por staff/status. Los composites existentes tienen staff_id/status
  entre medio, asi que una query solo por (store_id, rango de fecha) no los
  aprovecha.
- colas outbox_messages / webhook_inbox: indices PARCIALES sobre los pendientes
  (processed_at IS NULL), que es lo unico que barre el poller en cada tick.
- notifications (store_id, created_at): la campanita ordena por created_at DESC
  dentro de la tienda.
- otp_verifications (store_id, phone, created_at): busqueda del ultimo codigo por
  telefono.

Revision ID: a1c3e5f7b9d0
Revises: f4a5b6c7d8e9
Create Date: 2026-09-03 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c3e5f7b9d0"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_appointments_store_starts_at",
        "appointments",
        ["store_id", "starts_at"],
        unique=False,
    )
    op.create_index(
        "ix_outbox_pending",
        "outbox_messages",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("processed_at IS NULL"),
    )
    op.create_index(
        "ix_webhook_inbox_pending",
        "webhook_inbox",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("processed_at IS NULL"),
    )
    op.create_index(
        "ix_notifications_store_created",
        "notifications",
        ["store_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_otp_store_phone_created",
        "otp_verifications",
        ["store_id", "phone", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_otp_store_phone_created", table_name="otp_verifications")
    op.drop_index("ix_notifications_store_created", table_name="notifications")
    op.drop_index("ix_webhook_inbox_pending", table_name="webhook_inbox")
    op.drop_index("ix_outbox_pending", table_name="outbox_messages")
    op.drop_index("ix_appointments_store_starts_at", table_name="appointments")
