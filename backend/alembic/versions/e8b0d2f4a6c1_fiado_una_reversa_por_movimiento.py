"""customer_ledger.reverses_id unico: un movimiento se revierte una sola vez

Decision de Mateo (2026-10-03): el panel ofrece "Revertir" en cada
movimiento del fiado. La unica guarda contra dos reversas del mismo movimiento
era el ``pg_advisory_xact_lock`` por (tienda, cliente) de
``modules/ledger/service.py`` mas el SELECT "ya fue revertido" que corre
despues; ``ix_customer_ledger_reverses_id`` no era unico. Un camino nuevo que
escriba una reversa sin ese lock (o con otra clave) duplicaria la anulacion y
dejaria el saldo corrido. El indice unico lo sostiene en la base, sin depender
de que cada escritor se acuerde del lock (CLAUDE.md, principio rector).
Los NULL no chocan entre si: un movimiento comun no es reversa de nadie.

Reemplaza al indice comun (mismas consultas: el EXISTS de ``reversed`` y el
chequeo del service). ``CONCURRENTLY`` en ``autocommit_block`` con ``DROP
INDEX CONCURRENTLY IF EXISTS`` antes: un intento anterior cortado deja un
indice INVALID con el mismo nombre. Si ya hubiera reversas duplicadas, se
detiene con el conteo: esta migracion no decide cual conservar.

El downgrade vuelve al indice comun; el codigo anterior no depende de que sea
unico.

Revision ID: e8b0d2f4a6c1
Revises: a7c9e1b3d5f2
Create Date: 2026-10-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "e8b0d2f4a6c1"
down_revision: Union[str, Sequence[str], None] = "a7c9e1b3d5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNICO = "uq_customer_ledger_reverses_id"
COMUN = "ix_customer_ledger_reverses_id"


def _reversas_duplicadas() -> int:
    # En modo offline (`alembic upgrade --sql`) no hay conexion para contar:
    # el chequeo lo hace el propio CREATE UNIQUE INDEX.
    if context.is_offline_mode():
        return 0
    return int(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM ("
                "  SELECT reverses_id FROM customer_ledger "
                "  WHERE reverses_id IS NOT NULL "
                "  GROUP BY reverses_id HAVING count(*) > 1"
                ") AS d"
            )
        )
        .scalar()
        or 0
    )


def upgrade() -> None:
    duplicadas = _reversas_duplicadas()
    if duplicadas:
        raise RuntimeError(
            f"customer_ledger tiene {duplicadas} movimiento(s) revertido(s) mas "
            "de una vez. Esta migracion no decide que reversa conservar: "
            "corregir esas filas a mano y volver a correr `alembic upgrade head`."
        )
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {UNICO}")
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY {UNICO} ON customer_ledger (reverses_id)"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {COMUN}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {COMUN}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY {COMUN} ON customer_ledger (reverses_id)"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {UNICO}")
