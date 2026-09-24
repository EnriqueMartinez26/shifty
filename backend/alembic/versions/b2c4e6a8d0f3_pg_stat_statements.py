"""extension pg_stat_statements (plan de rendimiento, R7-04)

Sin ella no hay forma de saber que consultas consumen la base con el trafico
real: los EXPLAIN de ``tests/postgres`` dicen que indice PUEDE usar una
consulta, no cuanto pesa. compose la precarga (``shared_preload_libraries``)
en dev y en prod; aca solo se crea la extension en la base. La crea el rol de
migracion (superusuario: la extension no es ``trusted``); la lectura desde la
app o desde ops va con ``pg_read_all_stats``.

``CREATE EXTENSION`` no necesita la precarga para crearse; sin ella la vista
existe pero consultarla falla, que es lo esperable en un servidor que no la
precarga.

Revision ID: b2c4e6a8d0f3
Revises: c8e0a2b4d6f9
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b2c4e6a8d0f3"
down_revision: Union[str, Sequence[str], None] = "c8e0a2b4d6f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_stat_statements")
