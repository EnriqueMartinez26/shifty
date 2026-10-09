"""appointment_balance_payments: el resto de un turno pagado aparte (D-20261008-01)

Saldo restante por turno, opcion A (propuesta por Mateo, aprobada por Mateo y
Enrique el 2026-10-08). Un turno tiene a lo sumo un cobro y ese cobro
acreditado puede ser menor que el precio congelado (una sena de $960 sobre un
servicio de $3.200). El resto que el cliente paga en el local ($2.240) se
registra en esta tabla: un resto VIVO por turno, por un importe mayor a cero,
con medio de pago opcional. Revertirlo (la devolucion se hace fuera del
sistema) lo marca, no lo borra.

Expand puro (docs/DEPLOY_RUNBOOK.md, seccion 5): tabla nueva, sin tocar las
existentes. La tabla nace vacia, asi que sus indices se crean en la misma
transaccion (no es una tabla viva: no hace falta CONCURRENTLY). RLS forzada con
la misma politica que las demas tablas con ``store_id`` (el admin global ve
todo, el resto solo su tienda); los permisos del rol de la app llegan por los
DEFAULT PRIVILEGES de ``c3d4e5f6a7b8``.

- ``uq_appointment_balance_payments_live``: unico parcial por turno entre los
  no revertidos. Es la ultima defensa contra dos restos a la vez (el service
  ya los serializa con el lock del turno) y el camino del join por turno de
  reportes, panel y la busqueda de Cobros.
- ``ix_appointment_balance_payments_store_created``: la tienda y el orden de
  alta, para listar o auditar los restos de una tienda.

El downgrade borra la tabla: se pierden los restos registrados (el codigo
anterior no los lee ni los cuenta).

Revision ID: c7e9a1b3d5f8
Revises: b4d6f8a0c2e5
Create Date: 2026-10-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7e9a1b3d5f8"
down_revision: Union[str, Sequence[str], None] = "b4d6f8a0c2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "appointment_balance_payments"
METODOS = ("efectivo", "transferencia", "mercadopago", "otro")


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
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=True),
        sa.Column(
            "recorded_by", sa.String(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_appointment_balance_payments_amount"),
        sa.CheckConstraint(
            "method IS NULL OR method IN ("
            + ", ".join(f"'{m}'" for m in METODOS)
            + ")",
            name="ck_appointment_balance_payments_method",
        ),
        sa.CheckConstraint(
            "(reverted_at IS NULL) = (reverted_by IS NULL)",
            name="ck_appointment_balance_payments_reverted",
        ),
    )
    op.create_index(
        "uq_appointment_balance_payments_live",
        TABLA,
        ["appointment_id"],
        unique=True,
        postgresql_where=sa.text("reverted_at IS NULL"),
        sqlite_where=sa.text("reverted_at IS NULL"),
    )
    op.create_index(
        "ix_appointment_balance_payments_store_created",
        TABLA,
        ["store_id", "created_at"],
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
    op.drop_index("ix_appointment_balance_payments_store_created", table_name=TABLA)
    op.drop_index("uq_appointment_balance_payments_live", table_name=TABLA)
    op.drop_table(TABLA)
