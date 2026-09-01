"""congelar precio del turno y permitir revertir movimientos de fiado

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b8
Create Date: 2026-09-01 00:00:00.000000

Dos cambios funcionales:

- ``appointments.price_amount``: congela el precio de lista al momento de
  reservar. El reporte de ingresos y el cobro manual usan este valor, no el
  precio actual del servicio (que puede haber cambiado).
- ``customer_ledger.reverses_id``: apunta al movimiento que anula, de modo que
  un movimiento mal cargado se pueda revertir una unica vez.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("price_amount", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "customer_ledger",
        sa.Column("reverses_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_customer_ledger_reverses_id",
        "customer_ledger",
        ["reverses_id"],
    )
    op.create_foreign_key(
        "fk_customer_ledger_reverses_id",
        "customer_ledger",
        "customer_ledger",
        ["reverses_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_customer_ledger_reverses_id", "customer_ledger", type_="foreignkey"
    )
    op.drop_index("ix_customer_ledger_reverses_id", table_name="customer_ledger")
    op.drop_column("customer_ledger", "reverses_id")
    op.drop_column("appointments", "price_amount")
