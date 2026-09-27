"""services: VALIDATE del tope de duracion (revision de F1-13)

Segunda mitad de ``c3d5e7f9a1b4``. ``VALIDATE CONSTRAINT`` recorre la tabla con
``SHARE UPDATE EXCLUSIVE``: no frena lecturas ni escrituras. El downgrade
vuelve al CHECK sin validar.

Revision ID: d4e6f8a0b2c5
Revises: c3d5e7f9a1b4
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d4e6f8a0b2c5"
down_revision: Union[str, Sequence[str], None] = "c3d5e7f9a1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE services VALIDATE CONSTRAINT ck_services_duration_max")


def downgrade() -> None:
    op.execute("ALTER TABLE services DROP CONSTRAINT ck_services_duration_max")
    op.execute(
        "ALTER TABLE services ADD CONSTRAINT ck_services_duration_max "
        "CHECK (duration_minutes <= 1440) NOT VALID"
    )
