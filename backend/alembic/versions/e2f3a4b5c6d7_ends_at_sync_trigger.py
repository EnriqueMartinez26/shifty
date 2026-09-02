"""garantizar ends_at = starts_at + duration a nivel base

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-01 00:30:00.000000

``appointments.ends_at`` es una columna derivada (starts_at + duration_minutes)
que se materializa porque la respalda la exclusion constraint GiST anti-doble
reserva. Hasta ahora su consistencia dependia solo del codigo de aplicacion:
un UPDATE manual o un script podian dejarla desincronizada y corromper el
anti-overlap. Este trigger la fuerza en cada INSERT/UPDATE, igual que el trigger
de transiciones de estado. Es especifico de PostgreSQL; en SQLite (tests) se
omite.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ENDS_AT_SYNC = """
CREATE OR REPLACE FUNCTION shifty_sync_appointment_ends_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.ends_at := NEW.starts_at + make_interval(mins => NEW.duration_minutes);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(_ENDS_AT_SYNC)
    op.execute(
        """
        CREATE TRIGGER trg_appointment_ends_at_sync
        BEFORE INSERT OR UPDATE OF starts_at, duration_minutes ON appointments
        FOR EACH ROW
        EXECUTE FUNCTION shifty_sync_appointment_ends_at();
        """
    )
    # Corrige cualquier fila historica que hubiera quedado desincronizada.
    op.execute(
        """
        UPDATE appointments
        SET ends_at = starts_at + make_interval(mins => duration_minutes)
        WHERE ends_at IS DISTINCT FROM starts_at + make_interval(mins => duration_minutes)
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("DROP TRIGGER IF EXISTS trg_appointment_ends_at_sync ON appointments")
    op.execute("DROP FUNCTION IF EXISTS shifty_sync_appointment_ends_at()")
