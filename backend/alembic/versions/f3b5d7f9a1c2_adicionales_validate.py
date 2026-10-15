"""appointments.addons_amount: VALIDATE del CHECK

Segunda mitad de ``e2a4c6e8f0b1``. ``VALIDATE CONSTRAINT`` recorre la tabla con
``SHARE UPDATE EXCLUSIVE``: no frena lecturas ni escrituras de la app. Va en su
propia revision (una transaccion por revision, ``alembic/env.py``) para que el
lock fuerte del ``ADD CONSTRAINT`` no se sostenga durante el recorrido.

Toda fila previa tiene ``addons_amount`` = 0 (el default de la columna) y
``price_amount`` NULL o mayor o igual a cero, asi que valida sin cambios.

El downgrade vuelve al estado de la revision anterior: el CHECK sin validar.

Revision ID: f3b5d7f9a1c2
Revises: e2a4c6e8f0b1
Create Date: 2026-10-14
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f3b5d7f9a1c2"
down_revision: Union[str, Sequence[str], None] = "e2a4c6e8f0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK_TURNO = "ck_appointments_addons_amount"


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
        "CHECK (addons_amount >= 0 AND "
        "(price_amount IS NULL OR price_amount >= addons_amount)) NOT VALID"
    )
