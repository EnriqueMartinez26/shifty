"""appointments: VALIDATE del tope de duracion (F1-13, R7-02)

Segunda mitad de ``e9f1b3d5a7c0``. ``VALIDATE CONSTRAINT`` recorre la tabla con
``SHARE UPDATE EXCLUSIVE``: no frena lecturas ni escrituras de la app. El
downgrade vuelve al estado de la revision anterior: el CHECK sin validar.

Revision ID: f0a2c4e6b8d1
Revises: e9f1b3d5a7c0
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f0a2c4e6b8d1"
down_revision: Union[str, Sequence[str], None] = "e9f1b3d5a7c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE appointments VALIDATE CONSTRAINT ck_appointments_max_span")


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP CONSTRAINT ck_appointments_max_span")
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT ck_appointments_max_span "
        "CHECK (ends_at <= starts_at + interval '1 day') NOT VALID"
    )
