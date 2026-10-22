"""services.requires_prior_design + prior_design_message: diseno previo

Pedido de Mateo (2026-10-21, portal publico): un servicio puede pedirle al
cliente que mande su diseno antes del turno, con un mensaje que sale en el
portal. Es solo un dato del servicio; el cobro y la sena no cambian.

- ``requires_prior_design``: NOT NULL con default constante ``false``, que en
  Postgres 11+ no reescribe la tabla (solo catalogo).
- ``prior_design_message``: ``varchar(500)`` nullable, sin default.

Expand puro (docs/DEPLOY_RUNBOOK.md, seccion 5): el codigo anterior no lee
ninguna de las dos y sus INSERT toman el default, asi que la ventana del
deploy (codigo viejo sobre el esquema nuevo) y el rollback sin migrar siguen
sirviendo. Sin backfill: el default cubre las filas existentes.

El downgrade borra las dos columnas: se pierde que servicio pedia diseno
previo y su mensaje.

Revision ID: a7c9e1b3d5f7
Revises: c9e1a3b5d7f2
Create Date: 2026-10-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c9e1b3d5f7"
down_revision: Union[str, Sequence[str], None] = "c9e1a3b5d7f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "services",
        sa.Column(
            "requires_prior_design",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "services",
        sa.Column("prior_design_message", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("services", "prior_design_message")
    op.drop_column("services", "requires_prior_design")
