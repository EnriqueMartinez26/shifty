"""payments.link_ref y payments.reconciled_at (revision de perf/f4-pay)

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

``reconciled_at`` (revision de 3b977a9..6c84d46, #4; se agrego aca porque la
migracion todavia no se libero): ultima consulta de la conciliacion a MP por
el cobro. La cola se ordena ``reconciled_at NULLS FIRST, created_at``: los
cobros que siguen ``pending`` en MP ya no ocupan siempre el frente. Mismo
expand puro: nullable, sin default ni backfill (NULL = nunca consultado, va
primero). Sin indice nuevo: el candidato sigue siendo el mismo conjunto de
cobros pendientes de ``ix_payments_status`` y el orden es un top-N sobre el
(antes tambien se ordenaba por ``created_at`` sin indice).

El downgrade quita las dos columnas: los links con nonce en vuelo dejan de
poder distinguirse (el codigo de esa version tampoco los genera) y la
conciliacion vuelve al orden por ``created_at``.

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
    op.add_column(
        "payments",
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payments", "reconciled_at")
    op.drop_column("payments", "link_ref")
