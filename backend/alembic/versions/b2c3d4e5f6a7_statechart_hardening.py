"""statechart hardening: optimistic locking y trigger de transiciones

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-25

Lleva la maquina de estados desde la disciplina del programador hasta la base:

- ``version`` en appointments y payments para optimistic locking.
- Un trigger BEFORE UPDATE que rechaza transiciones ilegales de
  ``appointments.status``. El CHECK existente solo validaba pertenencia al
  alfabeto; esto valida el grafo, y sobrevive a un script de mantenimiento o a
  un UPDATE manual en produccion.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# El grafo replicado en SQL. Debe mantenerse en sintonia con
# ALLOWED_STATUS_TRANSITIONS en infrastructure/persistence/models/appointment.py
_TRANSITION_GUARD = """
CREATE OR REPLACE FUNCTION shifty_check_appointment_transition()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
        RETURN NEW;
    END IF;

    IF NOT (
        (OLD.status = 'pending' AND NEW.status IN
            ('confirmed', 'cancelled', 'pending_payment', 'expired'))
        OR (OLD.status = 'pending_payment' AND NEW.status IN
            ('confirmed', 'cancelled', 'expired'))
        OR (OLD.status = 'confirmed' AND NEW.status IN
            ('completed', 'cancelled', 'absent'))
    ) THEN
        RAISE EXCEPTION
            'Transicion de turno invalida: % -> %', OLD.status, NEW.status
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "payments",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    # El trigger es especifico de PostgreSQL; en SQLite (tests) se omite.
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(_TRANSITION_GUARD)
    op.execute(
        """
        CREATE TRIGGER trg_appointment_transition_guard
        BEFORE UPDATE OF status ON appointments
        FOR EACH ROW
        EXECUTE FUNCTION shifty_check_appointment_transition();
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_appointment_transition_guard ON appointments"
        )
        op.execute("DROP FUNCTION IF EXISTS shifty_check_appointment_transition()")

    op.drop_column("payments", "version")
    op.drop_column("appointments", "version")
