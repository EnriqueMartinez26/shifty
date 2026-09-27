"""marketing_opt_outs: baja del mail promocional por cliente y tienda (art. 27)

2026-09-25, L3-05 y L1 (O-8). El mail "volve a reservar" es promocional y la
Ley 25.326 (art. 27) exige poder pedir el retiro en cualquier momento. La
baja llega por un link firmado del mail (``GET /public/unsubscribe``) y
queda aca; el lote del outbox no manda ese mail a quien figura.

Expand puro (docs/DEPLOY_RUNBOOK.md, seccion 5): tabla nueva. Una fila por
cliente y tienda (``uq_marketing_opt_outs_store_client``, que ademas sirve la
consulta por tienda del lote). RLS forzada con la misma politica que las
demas tablas con ``store_id``; los permisos del rol de la app llegan por los
DEFAULT PRIVILEGES de ``c3d4e5f6a7b8``.

El downgrade borra la tabla: se pierden las bajas (el codigo anterior
tampoco las respetaba).

Revision ID: e1a3c5e7b9d2
Revises: d9f1b3c5e7a0
Create Date: 2026-09-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1a3c5e7b9d2"
down_revision: Union[str, Sequence[str], None] = "d9f1b3c5e7a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "marketing_opt_outs"


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
        sa.Column("opted_out_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "store_id", "client_id", name="uq_marketing_opt_outs_store_client"
        ),
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
