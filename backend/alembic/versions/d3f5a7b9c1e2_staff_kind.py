"""staff.kind (persona o recurso) y email opcional

Una cancha, una sala o un box tambien son "un calendario reservable": toda la
maquinaria (disponibilidad, lock, exclusion GiST, bloqueos, reportes) esta
indexada por staff_id, no por nada humano. Lo unico que ataba la tabla a una
persona era el email obligatorio (unico global) y el usuario con login que se
creaba al lado. ``kind='resource'`` no crea usuario ni exige email.

Revision ID: d3f5a7b9c1e2
Revises: c2e4f6a8b0d1
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3f5a7b9c1e2"
down_revision: Union[str, Sequence[str], None] = "c2e4f6a8b0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "staff",
        sa.Column(
            "kind", sa.String(length=20), nullable=False, server_default="person"
        ),
    )
    op.create_check_constraint(
        "ck_staff_kind", "staff", "kind IN ('person', 'resource')"
    )
    op.alter_column(
        "staff", "email", existing_type=sa.String(length=255), nullable=True
    )


def downgrade() -> None:
    # Reponer el NOT NULL exige que ninguna fila quede con email nulo.
    op.execute("UPDATE staff SET email = '' WHERE email IS NULL")
    op.alter_column(
        "staff", "email", existing_type=sa.String(length=255), nullable=False
    )
    op.drop_constraint("ck_staff_kind", "staff", type_="check")
    op.drop_column("staff", "kind")
