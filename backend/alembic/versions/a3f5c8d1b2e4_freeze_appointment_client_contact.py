"""freeze_appointment_client_contact

Revision ID: a3f5c8d1b2e4
Revises: c2e4f6a8b0d1
Create Date: 2026-09-11 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a3f5c8d1b2e4"
down_revision: Union[str, Sequence[str], None] = "c2e4f6a8b0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Los datos de contacto del turno se congelan al reservar: ya no se
    # derivan en vivo del usuario vinculado (ver appointment.py). Nace
    # nullable para poder backfillear los turnos existentes antes de
    # exigir NOT NULL.
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS client_name VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS client_email VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS client_phone VARCHAR(50)"
    )

    # Backfill desde el usuario vinculado (si lo hay). 'Cliente' es el
    # ultimo recurso para turnos sin client_id o sin nombre/email de
    # usuario, asi la columna puede pasar a NOT NULL sin perder filas.
    op.execute(
        """
        UPDATE appointments a
        SET client_name = COALESCE(
                NULLIF(TRIM(CONCAT_WS(' ', u.first_name, u.last_name)), ''),
                NULLIF(TRIM(u.email), ''),
                'Cliente'
            ),
            client_email = NULLIF(TRIM(u.email), ''),
            client_phone = NULLIF(TRIM(u.phone), '')
        FROM users u
        WHERE a.client_id = u.id
        """
    )
    op.execute(
        "UPDATE appointments SET client_name = 'Cliente' WHERE client_name IS NULL"
    )

    op.execute("ALTER TABLE appointments ALTER COLUMN client_name SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS client_phone")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS client_email")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS client_name")
