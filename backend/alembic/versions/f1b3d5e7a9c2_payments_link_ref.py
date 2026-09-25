"""payments.link_ref: nonce del link de pago vigente (revision de perf/f4-pay)

2026-09-25. El pago de Mercado Pago no trae ``preference_id``: la integridad
del webhook no podia distinguir un pago del link VIEJO de uno del link nuevo
de un cobro regenerado (misma ``external_reference`` = id del turno, misma
``metadata``). Cada link nuevo lleva ahora un nonce en su
``external_reference`` (``<turno>:<link_ref>``) y el cobro guarda el del link
vigente en ``link_ref``.

Expand puro (docs/DEPLOY_RUNBOOK.md, seccion 5): columna nueva, nullable, sin
default ni backfill. En Postgres es un cambio de catalogo (lock breve, sin
reescribir la tabla; si no consigue el lock aborta a los 3 s por el
``lock_timeout`` de ``alembic/env.py``). NULL = link creado antes de la
columna: su referencia sigue siendo el id del turno. El codigo anterior no
lee la columna, asi que un rollback sin migrar no se entera de ella; la
generacion del nonce la prende despues ``MERCADOPAGO_LINK_REF_ENABLED``.

El downgrade quita la columna: los links con nonce en vuelo dejan de poder
distinguirse (el codigo de esa version tampoco los genera).

Revision ID: f1b3d5e7a9c2
Revises: e7a9c1d3f5b8
Create Date: 2026-09-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1b3d5e7a9c2"
down_revision: Union[str, Sequence[str], None] = "e7a9c1d3f5b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("link_ref", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payments", "link_ref")
