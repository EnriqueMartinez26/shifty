"""service_addons + appointments.addons_*: adicionales con precio por servicio

Decision de Mateo (2026-10-14): un adicional suma PRECIO, nunca tiempo (la
duracion del servicio ya cubre el maximo). El turno congela el total en
``price_amount`` (como ya lo hacia con el precio con promo), la parte de los
adicionales en ``addons_amount`` y las lineas elegidas en ``addons_snapshot``.

Expand puro (docs/DEPLOY_RUNBOOK.md, seccion 5):

- ``service_addons``: tabla nueva. Nace vacia, asi que su indice se crea en la
  misma transaccion (no es una tabla viva: no hace falta CONCURRENTLY; mismo
  criterio que ``c7e9a1b3d5f8``). RLS forzada con la politica de siempre (el
  admin global ve todo, el resto solo su tienda); los permisos del rol de la
  app llegan por los DEFAULT PRIVILEGES de ``c3d4e5f6a7b8``.
- ``appointments.addons_amount``: NOT NULL con default constante, que en
  Postgres 11+ no reescribe la tabla (solo catalogo). ``addons_snapshot``:
  nullable, sin default.
- ``ck_appointments_addons_amount`` (``addons_amount >= 0``): se agrega
  ``NOT VALID`` (lock breve, no recorre la tabla); ``f3b5d7f9a1c2`` lo valida
  aparte, con un lock que no frena lecturas ni escrituras (patron
  ``c4e6a8b0d2f1`` + ``d5f7b9c1e3a2``). No exige ``price_amount >=
  addons_amount``: la promo se aplica al total (decision de Mateo,
  2026-10-15) y ``addons_amount`` es la suma SIN descuento de las lineas del
  snapshot, asi que un descuento grande deja el total por debajo de los
  adicionales sin que nada este mal.

El codigo anterior no lee nada de esto: la ventana del deploy (codigo viejo
sobre el esquema nuevo) y el rollback sin migrar siguen sirviendo. Un turno
que el codigo viejo reprograme nace con ``addons_amount`` = 0 y el
``price_amount`` copiado (el total): el CHECK se sigue cumpliendo.

El downgrade borra la tabla y las columnas: se pierden los adicionales
cargados y el detalle de los turnos que los eligieron (su total queda en
``price_amount``).

Revision ID: e2a4c6e8f0b1
Revises: d1f3a5c7e9b2
Create Date: 2026-10-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2a4c6e8f0b1"
down_revision: Union[str, Sequence[str], None] = "d1f3a5c7e9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "service_addons"
CHECK_TURNO = "ck_appointments_addons_amount"


def _crear_tabla() -> None:
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
            "service_id", sa.String(), sa.ForeignKey("services.id"), nullable=False
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("max_quantity", sa.Integer(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "unit_price >= 0 AND unit_price <= 1000000",
            name="ck_service_addons_unit_price",
        ),
        sa.CheckConstraint(
            "max_quantity >= 1 AND max_quantity <= 99",
            name="ck_service_addons_max_quantity",
        ),
        sa.CheckConstraint("length(name) > 0", name="ck_service_addons_name"),
        sa.CheckConstraint(
            "position >= 0 AND position <= 19", name="ck_service_addons_position"
        ),
    )
    op.create_index(
        "ix_service_addons_store_service",
        TABLA,
        ["store_id", "service_id", "position"],
    )


def _rls() -> None:
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


def upgrade() -> None:
    _crear_tabla()
    op.add_column(
        "appointments",
        sa.Column(
            "addons_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "appointments", sa.Column("addons_snapshot", sa.JSON(), nullable=True)
    )

    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"ALTER TABLE appointments ADD CONSTRAINT {CHECK_TURNO} "
        "CHECK (addons_amount >= 0) NOT VALID"
    )
    _rls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"ALTER TABLE appointments DROP CONSTRAINT IF EXISTS {CHECK_TURNO}")
        op.execute(f"DROP POLICY IF EXISTS {TABLA}_rls_policy ON {TABLA}")
    op.drop_column("appointments", "addons_snapshot")
    op.drop_column("appointments", "addons_amount")
    op.drop_index("ix_service_addons_store_service", table_name=TABLA)
    op.drop_table(TABLA)
