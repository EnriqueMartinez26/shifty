"""appointment_blocks: indice (store_id, staff_id, end_time) (F1-13, R7-02)

Los bloqueos no tienen tope de un dia (duran hasta 366, ``MAX_BLOCK_DURATION``),
asi que su cota inferior no puede salir de un tope de duracion: es la propia
``end_time > inicio`` del solapamiento. Sin un indice que la lleve, la consulta
caia en ``ix_appointment_blocks_staff_id`` y leia TODOS los bloqueos del
profesional, pasados incluidos, en cada alta, reserva y consulta de agenda. Con
``(store_id, staff_id, end_time)`` la condicion de indice es tienda +
profesional + ``end_time > inicio`` (todas leakproof bajo RLS) y solo quedan
los bloqueos vigentes o futuros; ``start_time < fin`` queda como filtro.

``CONCURRENTLY`` en ``autocommit_block`` (no toma el lock que frena escrituras)
con ``DROP INDEX CONCURRENTLY IF EXISTS`` antes: un intento anterior cortado
deja un indice INVALID con el mismo nombre.

Revision ID: a1b3d5f7c9e2
Revises: f0a2c4e6b8d1
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a1b3d5f7c9e2"
down_revision: Union[str, Sequence[str], None] = "f0a2c4e6b8d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDICE = "ix_appointment_blocks_store_staff_end"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDICE}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY {INDICE} "
            "ON appointment_blocks (store_id, staff_id, end_time)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDICE}")
