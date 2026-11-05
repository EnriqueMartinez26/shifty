"""stores.contact_email: el Reply-To de los mails al cliente

#283 (decision de Mateo, 2026-11-02): los mails al cliente salian de
``EMAILS_FROM_EMAIL`` sin ``Reply-To`` y la respuesta de una clienta caia en
el buzon de Shifty. La tienda carga un "Mail de contacto" opcional desde el
panel (``PATCH /stores/me``, que lo valida y normaliza) y los mails al cliente
lo llevan como ``Reply-To`` cuando es entregable.

Expand puro (docs/DEPLOY_RUNBOOK.md, seccion 5): columna nueva NULLABLE sin
default, solo catalogo en Postgres, sin reescribir la tabla. El codigo
anterior no la lee, asi que la ventana del deploy y el rollback sin migrar no
cambian nada. Sin indice: nadie busca tiendas por este campo.

El downgrade borra la columna: los mails vuelven a salir sin ``Reply-To``.

Revision ID: e2b4d6f8a0c3
Revises: a9c1e3f5b7d9
Create Date: 2026-11-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2b4d6f8a0c3"
down_revision: Union[str, Sequence[str], None] = "a9c1e3f5b7d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stores",
        sa.Column("contact_email", sa.String(length=254), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stores", "contact_email")
