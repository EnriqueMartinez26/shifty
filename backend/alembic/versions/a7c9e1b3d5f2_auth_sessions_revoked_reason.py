"""auth_sessions.revoked_reason: distinguir la rotacion de las demas revocaciones

2026-09-28, D-20260928-01. Reusar un refresh revocado por ROTACION hace menos
de ``REFRESH_REUSE_GRACE_SECONDS`` es una carrera propia (dos pestanas, un
reintento tras una respuesta perdida) y responde 401 sin cerrar las demas
sesiones del usuario. Para eso hace falta saber POR QUE se revoco la fila:
``'rotated'`` la escribe la rotacion; NULL es cualquier otra revocacion
(logout, admin, cambio de clave), que conserva la politica de revocar todo.

Expand puro (docs/DEPLOY_RUNBOOK.md, seccion 5): columna nullable sin default,
sin reescritura de la tabla. Las filas ya revocadas quedan en NULL, o sea
"no rotacion": el codigo nuevo las trata como hasta hoy.

El downgrade borra la columna: el codigo anterior no la lee.

Revision ID: a7c9e1b3d5f2
Revises: e1a3c5e7b9d2
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c9e1b3d5f2"
down_revision: Union[str, Sequence[str], None] = "e1a3c5e7b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column("revoked_reason", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("auth_sessions", "revoked_reason")
