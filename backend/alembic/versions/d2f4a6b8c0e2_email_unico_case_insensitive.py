"""email unico case-insensitive

- ``uq_users_email_lower``: indice unico funcional sobre ``lower(email)``.
  El login busca con ``func.lower(User.email)`` y ``scalar_one_or_none``:
  dos filas que difieran solo en mayusculas lo rompen con
  MultipleResultsFound (500). La columna ``email`` ya es unica pero
  case-sensitive, asi que la garantia real de la identidad vivia en tres
  normalizaciones repetidas en Python (staff, superadmin, auth) y el alta por
  ``POST /users/`` no era una de ellas. Este indice la lleva a la base.

Si la base ya tiene emails que solo difieren en mayusculas, la migracion NO
borra nada: se detiene con el conteo para que alguien decida cual fila
conservar.

Revision ID: d2f4a6b8c0e2
Revises: c9e1f3a5b7d9
Create Date: 2026-09-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "d2f4a6b8c0e2"
down_revision: Union[str, Sequence[str], None] = "c9e1f3a5b7d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # En modo offline (`alembic upgrade --sql`) no hay conexion para contar:
    # se emite el DDL y el chequeo lo hace el propio CREATE UNIQUE INDEX.
    duplicados = (
        0
        if context.is_offline_mode()
        else op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM ("
                "  SELECT lower(email) FROM users "
                "  GROUP BY lower(email) HAVING count(*) > 1"
                ") AS d"
            )
        )
        .scalar()
    )
    if duplicados:
        raise RuntimeError(
            f"users tiene {duplicados} email(s) repetidos salvo mayusculas. Esta "
            "migracion no decide cual conservar: unificar esas filas a mano y "
            "volver a correr `alembic upgrade head`."
        )
    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_users_email_lower", table_name="users")
