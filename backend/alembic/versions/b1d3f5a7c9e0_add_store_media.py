"""add_store_media

Tabla para imagenes subidas por la tienda (logo/portada), guardadas en bytea y
aisladas por RLS igual que el resto de las tablas de negocio. La lectura publica
(portal de reservas) se sirve por id desde el backend.

Revision ID: b1d3f5a7c9e0
Revises: a1c3e5f7b9d0
Create Date: 2026-09-03 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1d3f5a7c9e0"
down_revision: Union[str, Sequence[str], None] = "a1c3e5f7b9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "shifty_app"

_POLITICA = """
CREATE POLICY store_media_rls_policy ON store_media
USING (
    current_setting('app.is_global_admin', true) = 'true'
    OR store_id::text = current_setting('app.current_store_id', true)
)
"""


def upgrade() -> None:
    op.create_table(
        "store_media",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("store_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("content_type", sa.String(length=50), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_store_media_store_id", "store_media", ["store_id"], unique=False
    )

    if op.get_bind().dialect.name != "postgresql":
        return

    # Mismo aislamiento que el resto: RLS forzado + politica por store_id, y los
    # permisos para el rol de la app (NOBYPASSRLS).
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON store_media TO " + APP_ROLE)
    op.execute("ALTER TABLE store_media ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE store_media FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS store_media_rls_policy ON store_media")
    op.execute(_POLITICA)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS store_media_rls_policy ON store_media")
    op.drop_index("ix_store_media_store_id", table_name="store_media")
    op.drop_table("store_media")
