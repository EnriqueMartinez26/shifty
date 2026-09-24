"""indices parciales para la purga de retencion (F1-19)

Revision de perf/f2b (2026-09-24): la purga diaria
(``modules/housekeeping/retention.py``) filtra ``outbox_messages`` y
``webhook_inbox`` por ``processed_at`` y ``notifications`` por ``read_at``,
y ninguna de las tres tenia indice sobre esas columnas para las filas ya
procesadas o leidas (solo parciales de pendientes y no leidas). Cada lote de
5.000 recorria la tabla entera. Los parciales tienen solo el historico, que es
lo que la purga lee.

``CONCURRENTLY`` dentro de ``autocommit_block`` (sin el lock que frena
escrituras) y ``DROP INDEX CONCURRENTLY IF EXISTS`` antes de cada ``CREATE``:
un intento cortado deja un indice INVALID con el mismo nombre. Lo verifica
``tests/postgres/test_pg_retencion_indices.py``.

Revision ID: e5f7a9b1c3d6
Revises: d4e6f8a0b2c5
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e5f7a9b1c3d6"
down_revision: Union[str, Sequence[str], None] = "d4e6f8a0b2c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NUEVOS = {
    "ix_outbox_processed_history": (
        "outbox_messages (processed_at) WHERE processed_at IS NOT NULL"
    ),
    "ix_webhook_inbox_processed_history": (
        "webhook_inbox (processed_at) WHERE processed_at IS NOT NULL"
    ),
    "ix_notifications_read_history": (
        "notifications (read_at) WHERE read_at IS NOT NULL"
    ),
}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for nombre, definicion in NUEVOS.items():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")
            op.execute(f"CREATE INDEX CONCURRENTLY {nombre} ON {definicion}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for nombre in NUEVOS:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")
