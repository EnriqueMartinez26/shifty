"""users.email en minusculas: VALIDATE del CHECK (F1-12, R7-01)

Segunda mitad de ``c4e6a8b0d2f1``. ``VALIDATE CONSTRAINT`` recorre la tabla con
``SHARE UPDATE EXCLUSIVE``: no frena lecturas ni escrituras de la app. Va en su
propia revision (una transaccion por revision, ``alembic/env.py``) para que el
lock fuerte del ``ADD CONSTRAINT`` no se sostenga durante el recorrido.

El downgrade vuelve al estado de la revision anterior: el CHECK sin validar.

Revision ID: d5f7b9c1e3a2
Revises: c4e6a8b0d2f1
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d5f7b9c1e3a2"
down_revision: Union[str, Sequence[str], None] = "c4e6a8b0d2f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users VALIDATE CONSTRAINT ck_users_email_lower")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_email_lower")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_email_lower "
        "CHECK (email = lower(email)) NOT VALID"
    )
