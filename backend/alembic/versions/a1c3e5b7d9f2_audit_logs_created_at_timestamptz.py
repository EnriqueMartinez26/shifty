"""audit_logs.created_at pasa de timestamp naive a timestamptz

Era la unica marca temporal del esquema sin zona, con ``server_default
now()`` (2026-09-18, B5-13; regla 24: persistencia en UTC). Los valores
existentes se interpretan como UTC: ``created_at AT TIME ZONE 'UTC'``
convierte la hora de pared guardada en el instante UTC equivalente, sin
depender del ``TimeZone`` de la sesion que corre la migracion. El
``downgrade`` hace el inverso (``AT TIME ZONE 'UTC'`` sobre un timestamptz
devuelve la hora de pared UTC), asi que ida y vuelta conserva el valor.

La tabla queda fuera de RLS a proposito (``c3d4e5f6a7b8_rls_efectivo``) y no
tiene triggers ni vistas que dependan del tipo; el indice
``ix_audit_logs_created_at`` lo reconstruye Postgres con el ALTER, y el
default ``now()`` sirve igual para ambos tipos.

Revision ID: a1c3e5b7d9f2
Revises: f8c0e2a4b6d8
Create Date: 2026-09-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c3e5b7d9f2"
down_revision: Union[str, Sequence[str], None] = "f8c0e2a4b6d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "audit_logs",
        "created_at",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    op.alter_column(
        "audit_logs",
        "created_at",
        type_=sa.DateTime(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
