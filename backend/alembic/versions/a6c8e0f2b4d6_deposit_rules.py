"""reglas de sena por antelacion e historial; motivo de la sena en el pago

Cuatro columnas en ``stores`` con CHECK (recargos en puntos porcentuales del
precio, dias de antelacion) y ``payments.deposit_rule`` como snapshot del
motivo. Las columnas viejas ``requires_deposit`` y ``deposit_percentage``
siguen muertas: nadie las lee; se limpian aparte.

Revision ID: a6c8e0f2b4d6
Revises: f5b7c9d1e3a5
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6c8e0f2b4d6"
down_revision: Union[str, Sequence[str], None] = "f5b7c9d1e3a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNAS = (
    ("deposit_far_notice_days", "deposit_far_notice_days BETWEEN 0 AND 365"),
    (
        "deposit_far_notice_extra_percent",
        "deposit_far_notice_extra_percent BETWEEN 0 AND 100",
    ),
    (
        "deposit_new_client_extra_percent",
        "deposit_new_client_extra_percent BETWEEN 0 AND 100",
    ),
    (
        "deposit_absent_client_extra_percent",
        "deposit_absent_client_extra_percent BETWEEN 0 AND 100",
    ),
)


def upgrade() -> None:
    for columna, regla in COLUMNAS:
        op.add_column(
            "stores",
            sa.Column(columna, sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_check_constraint(f"ck_stores_{columna}", "stores", regla)
    op.add_column("payments", sa.Column("deposit_rule", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "deposit_rule")
    for columna, _regla in reversed(COLUMNAS):
        op.drop_constraint(f"ck_stores_{columna}", "stores", type_="check")
        op.drop_column("stores", columna)
