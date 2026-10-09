"""payments.integrity_held_at: el job de vencimiento no reconsulta a un retenido

Seguimiento W2 de la PR #104 (2026-10-03). El job de retenciones vencidas
retiene el turno cuyo pago remoto MP da por APROBADO pero no pasa la
integridad, y avisa a Sentry una vez por pago. El turno seguia en la consulta
del job y se le volvia a preguntar a MP en CADA corrida (cada minuto), con el
presupuesto de 60 s de la fase A compartido: con decenas de retenidos (una
tienda con credenciales de prueba) las retenciones nuevas dejaban de vencer.

``integrity_held_at`` es la ultima vez que el job lo retuvo por integridad;
mientras sea de la ultima hora, la consulta no lo toma. Expand puro: nullable,
sin default ni backfill (NULL = nunca retenido, se consulta como siempre;
``ADD COLUMN`` sin default no reescribe la tabla). Sin indice: el predicado
filtra filas del outer join que ya eligio el indice de turnos.

El downgrade quita la columna: el codigo anterior no la conoce y vuelve a
consultar a los retenidos en cada corrida.

Revision ID: b4d6f8a0c2e5
Revises: e8b0d2f4a6c1
Create Date: 2026-10-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4d6f8a0c2e5"
down_revision: Union[str, Sequence[str], None] = "e8b0d2f4a6c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("integrity_held_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payments", "integrity_held_at")
