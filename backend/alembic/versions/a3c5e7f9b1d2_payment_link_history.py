"""payment_link_history: links de pago retirados de cada cobro (perf/f4-pay)

2026-09-25, revision de 7abb9b4..e5579b6. Un pago sobre un link que el cobro
ya retiro (regenerar un cobro vencido, re-tarifar) no se aplicaba ni se
conciliaba: el cobro seguia pendiente con el link nuevo vivo. Con
``binary_mode`` no hay cupones de efectivo pendientes; el caso es un pago en
el link retirado antes de que MP lo venza, o el webhook tardio, reentregado
o perdido de un pago hecho antes del retiro. Esta tabla guarda cada link retirado
(``link_ref``, ``preference_id``, importe y moneda de ESE link) para que el
webhook y la conciliacion lo reconozcan (``modules/payments/links.py``).
``original_amount``, ``discount_amount`` y ``promotion_code`` explican ese
importe: la adopcion del link los restaura (revision de e5579b6..3b977a9,
#3; se agregaron aca porque la migracion todavia no se libero).

Expand puro (docs/DEPLOY_RUNBOOK.md, seccion 5): tabla nueva, sin tocar las
existentes. RLS forzada con la misma politica que las demas tablas con
``store_id`` (el admin global ve todo, el resto solo su tienda); los permisos
del rol de la app llegan por los DEFAULT PRIVILEGES de ``c3d4e5f6a7b8``.
``ix_payment_link_history_payment_retired`` sirve la busqueda por cobro y
ventana; el indice de ``store_id`` va por el filtro de tienda.

El downgrade borra la tabla: se pierde el historial (el codigo anterior no lo
lee).

Revision ID: a3c5e7f9b1d2
Revises: f1b3d5e7a9c2
Create Date: 2026-09-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3c5e7f9b1d2"
down_revision: Union[str, Sequence[str], None] = "f1b3d5e7a9c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "payment_link_history"


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
        sa.Column(
            "payment_id", sa.String(), sa.ForeignKey("payments.id"), nullable=False
        ),
        sa.Column("link_ref", sa.String(length=40), nullable=True),
        sa.Column("preference_id", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("original_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("promotion_code", sa.String(length=50), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(f"ix_{TABLA}_store_id", TABLA, ["store_id"])
    op.create_index(
        "ix_payment_link_history_payment_retired", TABLA, ["payment_id", "retired_at"]
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
    op.drop_index("ix_payment_link_history_payment_retired", table_name=TABLA)
    op.drop_index(f"ix_{TABLA}_store_id", table_name=TABLA)
    op.drop_table(TABLA)
