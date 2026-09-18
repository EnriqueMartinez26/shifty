"""contador de intentos en outbox_messages

``outbox_messages.attempts``: cuantas veces fallo el consumidor del outbox
con este mensaje. Al llegar a ``WEBHOOK_INBOX_MAX_ATTEMPTS`` (el mismo techo
que el inbox de webhooks) el mensaje se da por procesado con su ``error``
anotado. Sin esto un mensaje que siempre falla se reintentaba cada minuto
para siempre y ocupaba lugar en cada lote (2026-09-17, B2-12).

Las filas existentes arrancan en 0: un mensaje que ya venia fallando tiene
por delante los intentos completos, no se abandona de golpe.

Revision ID: e7b9d1f3a5c7
Revises: d2f4a6b8c0e2
Create Date: 2026-09-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7b9d1f3a5c7"
down_revision: Union[str, Sequence[str], None] = "d2f4a6b8c0e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outbox_messages",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("outbox_messages", "attempts")
