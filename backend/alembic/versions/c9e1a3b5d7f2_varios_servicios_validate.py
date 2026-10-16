"""appointments.extra_services_amount: VALIDATE del CHECK

Segunda mitad de ``b8d0f2a4c6e1``. ``VALIDATE CONSTRAINT`` recorre la tabla con
``SHARE UPDATE EXCLUSIVE``: no frena lecturas ni escrituras de la app. Va en su
propia revision (una transaccion por revision, ``alembic/env.py``) para que el
lock fuerte del ``ADD CONSTRAINT`` no se sostenga durante el recorrido.

Toda fila previa tiene ``extra_services_amount`` = 0 (el default de la
columna), asi que valida sin cambios.

El downgrade vuelve al estado de la revision anterior: el CHECK sin validar.

Revision ID: c9e1a3b5d7f2
Revises: b8d0f2a4c6e1
Create Date: 2026-10-16
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c9e1a3b5d7f2"
down_revision: Union[str, Sequence[str], None] = "b8d0f2a4c6e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK_TURNO = "ck_appointments_extra_services_amount"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE appointments VALIDATE CONSTRAINT {CHECK_TURNO}")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE appointments DROP CONSTRAINT {CHECK_TURNO}")
    op.execute(
        f"ALTER TABLE appointments ADD CONSTRAINT {CHECK_TURNO} "
        "CHECK (extra_services_amount >= 0) NOT VALID"
    )
