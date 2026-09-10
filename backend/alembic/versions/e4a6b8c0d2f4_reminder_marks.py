"""marcas durables de recordatorio (24h y 2h) en appointments

El unico rastro de "recordatorio ya enviado" era una clave en Redis con
vencimiento de siete dias: si Redis se reiniciaba se reenviaban hasta dos
dias de recordatorios. Dos columnas nullable: la marca es durable, visible
al dueno, y el reclamo ``UPDATE ... WHERE col IS NULL`` es seguro entre
workers sin lock nuevo.

Revision ID: e4a6b8c0d2f4
Revises: d3f5a7b9c1e2
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4a6b8c0d2f4"
down_revision: Union[str, Sequence[str], None] = "d3f5a7b9c1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("reminder_24h_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("reminder_2h_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("appointments", "reminder_2h_sent_at")
    op.drop_column("appointments", "reminder_24h_sent_at")
