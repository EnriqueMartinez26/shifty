"""audit_logs.store_id: la tienda a la que pertenece cada entrada

``list_store_audit_logs`` traia las ``limit*4`` entradas de superadmin mas
recientes de todas las tiendas y filtraba en Python: si en esa ventana no
habia ninguna de la tienda pedida, el panel mostraba "sin actividad" para una
tienda que si la tuvo (2026-09-18, B3-11; regla 11). Con la columna el listado
filtra en SQL con un LIMIT real.

Backfill de las filas existentes desde el recurso auditado, cuando se puede
derivar:

- ``Store``             -> ``stores.id`` por ``stores.public_id``
- ``User``              -> ``users.store_id`` por ``users.id``
- ``StoreSubscription`` -> ``store_subscriptions.store_id``
- ``CouponRedemption``  -> ``coupon_redemptions.store_id``
- ``Appointment``       -> ``appointments.store_id``
- ``AppointmentBlock``  -> ``appointment_blocks.store_id``

Quedan en NULL, sin borrar ninguna fila: ``Plan`` y ``SaaSCoupon`` (son
globales, no pertenecen a una tienda) y cualquier fila cuyo recurso ya no
exista o cuyo tipo no este en la lista.

Las tablas de origen tienen RLS forzada: para que el backfill las lea completas
sea cual sea el rol que migra, en Postgres se fija ``app.is_global_admin`` con
``set_config(..., true)``, local a la transaccion de la migracion. La tabla
``audit_logs`` sigue fuera de RLS a proposito (``c3d4e5f6a7b8_rls_efectivo``).
Sin FK a ``stores``: un log es inmutable y sobrevive a su recurso.

Revision ID: c5e7a9b1d3f4
Revises: a1c3e5b7d9f2
Create Date: 2026-09-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5e7a9b1d3f4"
down_revision: Union[str, Sequence[str], None] = "a1c3e5b7d9f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDICE = "ix_audit_logs_store_id"

# (resource_type, subconsulta que devuelve el store_id del recurso auditado)
ORIGENES = (
    (
        "Store",
        "SELECT s.id FROM stores s WHERE s.public_id = audit_logs.resource_id",
    ),
    (
        "User",
        "SELECT u.store_id FROM users u WHERE u.id = audit_logs.resource_id",
    ),
    (
        "StoreSubscription",
        "SELECT ss.store_id FROM store_subscriptions ss "
        "WHERE ss.id = audit_logs.resource_id",
    ),
    (
        "CouponRedemption",
        "SELECT cr.store_id FROM coupon_redemptions cr "
        "WHERE cr.id = audit_logs.resource_id",
    ),
    (
        "Appointment",
        "SELECT a.store_id FROM appointments a WHERE a.id = audit_logs.resource_id",
    ),
    (
        "AppointmentBlock",
        "SELECT b.store_id FROM appointment_blocks b "
        "WHERE b.id = audit_logs.resource_id",
    ),
)


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("store_id", sa.String(), nullable=True))
    op.create_index(INDICE, "audit_logs", ["store_id"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute("SELECT set_config('app.is_global_admin', 'true', true)")
    for tipo, subconsulta in ORIGENES:
        op.execute(
            sa.text(
                f"UPDATE audit_logs SET store_id = ({subconsulta}) "
                "WHERE resource_type = :tipo AND store_id IS NULL"
            ).bindparams(tipo=tipo)
        )


def downgrade() -> None:
    op.drop_index(INDICE, table_name="audit_logs")
    op.drop_column("audit_logs", "store_id")
