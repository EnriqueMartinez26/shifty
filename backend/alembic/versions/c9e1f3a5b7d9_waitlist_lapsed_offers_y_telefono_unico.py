"""anti-acaparamiento de la lista de espera y telefono unico por tienda

- ``waitlist_entries.lapsed_offers``: cuantas ofertas dejo vencer una entrada.
  Al llegar a MAX_LAPSED_OFFERS expira sola; sin esto una cola llena de
  entradas que nunca reservan mataba cada cupo liberado en ofertas a nadie.
- ``uq_users_client_phone_per_store``: un telefono identifica a UN cliente por
  tienda. Dos filas iguales rompian ``get_or_create_client`` con
  MultipleResultsFound (500). El indice es parcial: solo clientes con
  telefono; el personal puede compartir el telefono del local.

Si la base ya tiene telefonos duplicados, la migracion NO borra nada: se
detiene con el conteo para que alguien decida cual fila conservar.

Revision ID: c9e1f3a5b7d9
Revises: f3a4a3162064
Create Date: 2026-09-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "c9e1f3a5b7d9"
down_revision: Union[str, Sequence[str], None] = "f3a4a3162064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONDICION = "role = 'client' AND phone IS NOT NULL"


def upgrade() -> None:
    op.add_column(
        "waitlist_entries",
        sa.Column("lapsed_offers", sa.Integer(), nullable=False, server_default="0"),
    )

    # En modo offline (`alembic upgrade --sql`) no hay conexion para contar:
    # se emite el DDL y el chequeo lo hace el propio CREATE UNIQUE INDEX.
    duplicados = (
        0
        if context.is_offline_mode()
        else op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM ("
                "  SELECT store_id, phone FROM users "
                f"  WHERE {_CONDICION} "
                "  GROUP BY store_id, phone HAVING count(*) > 1"
                ") AS d"
            )
        )
        .scalar()
    )
    if duplicados:
        raise RuntimeError(
            f"users tiene {duplicados} telefono(s) de cliente repetidos dentro de "
            "una misma tienda. Esta migracion no decide cual conservar: unificar "
            "esas filas a mano y volver a correr `alembic upgrade head`."
        )
    op.create_index(
        "uq_users_client_phone_per_store",
        "users",
        ["store_id", "phone"],
        unique=True,
        postgresql_where=sa.text(_CONDICION),
        sqlite_where=sa.text(_CONDICION),
    )


def downgrade() -> None:
    op.drop_index("uq_users_client_phone_per_store", table_name="users")
    op.drop_column("waitlist_entries", "lapsed_offers")
