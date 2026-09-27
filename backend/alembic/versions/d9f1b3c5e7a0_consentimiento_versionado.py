"""consentimiento versionado y aceptacion de los terminos B2B (PV-09, L1)

2026-09-25. ``terms_accepted_at`` sola no prueba que texto rigio, la lista de
espera no guardaba consentimiento y ninguna tienda aceptaba los terminos B2B.

Expand puro (docs/DEPLOY_RUNBOOK.md, seccion 5): solo agrega.

- ``appointments.terms_version`` y ``privacy_version`` (``varchar(20)``,
  nullable, sin default): las versiones que el cliente acepto en el portal.
- ``waitlist_entries.terms_accepted_at``, ``terms_version`` y
  ``privacy_version`` (nullable): el consentimiento al anotarse.
  Agregar una columna nullable sin default es un cambio de catalogo en
  Postgres (sin reescribir la tabla); el ``lock_timeout`` de 3 s cubre la
  espera del lock breve.
- ``store_terms_acceptances``: una fila por aceptacion (tienda, usuario,
  version, fecha, HMAC de la IP). RLS forzada con la misma politica que las
  demas tablas con ``store_id``; los permisos del rol de la app llegan por
  los DEFAULT PRIVILEGES de ``c3d4e5f6a7b8``.
  ``ix_store_terms_acceptances_store_accepted`` sirve "la ultima de la
  tienda" y el filtro por tienda.

El downgrade quita la tabla y las columnas: se pierden las versiones y las
aceptaciones registradas (el codigo anterior no las lee).

Revision ID: d9f1b3c5e7a0
Revises: c7e9a1b3d5f7
Create Date: 2026-09-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9f1b3c5e7a0"
down_revision: Union[str, Sequence[str], None] = "c7e9a1b3d5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "store_terms_acceptances"
INDICE = "ix_store_terms_acceptances_store_accepted"


def upgrade() -> None:
    op.add_column(
        "appointments", sa.Column("terms_version", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "appointments",
        sa.Column("privacy_version", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "waitlist_entries",
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "waitlist_entries",
        sa.Column("terms_version", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "waitlist_entries",
        sa.Column("privacy_version", sa.String(length=20), nullable=True),
    )

    op.create_table(
        TABLA,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("store_id", sa.String(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("terms_version", sa.String(length=20), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(INDICE, TABLA, ["store_id", "accepted_at"])

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
    op.drop_index(INDICE, table_name=TABLA)
    op.drop_table(TABLA)
    op.drop_column("waitlist_entries", "privacy_version")
    op.drop_column("waitlist_entries", "terms_version")
    op.drop_column("waitlist_entries", "terms_accepted_at")
    op.drop_column("appointments", "privacy_version")
    op.drop_column("appointments", "terms_version")
