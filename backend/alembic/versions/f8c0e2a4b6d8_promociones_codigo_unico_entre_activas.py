"""codigo de promocion unico solo entre las activas

``uq_store_promotions_store_code`` (UNIQUE sobre store_id, code) pasa a ser
el indice unico parcial ``uq_store_promotions_active_code`` con
``WHERE is_active``. El borrado de una promocion es logico y la restriccion
vieja dejaba su codigo inutilizable para siempre: recrear ``VERANO20``
despues de darla de baja respondia 409 sin ninguna promocion activa que lo
explicara (2026-09-17, B2-14). Los canjes conservan ``code_snapshot`` y
``promotion_id``: la trazabilidad no depende del codigo vivo.

``upgrade`` no puede encontrar conflictos: si la restriccion vieja se
cumplia, el indice parcial (mas laxo) tambien.

``downgrade`` SI puede: una vez reusado un codigo hay dos filas con el mismo
(store_id, code). La migracion NO borra ni renombra nada: se detiene con el
conteo para que alguien decida que hacer con las promociones historicas.

Revision ID: f8c0e2a4b6d8
Revises: e7b9d1f3a5c7
Create Date: 2026-09-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "f8c0e2a4b6d8"
down_revision: Union[str, Sequence[str], None] = "e7b9d1f3a5c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDICE = "uq_store_promotions_active_code"
_RESTRICCION = "uq_store_promotions_store_code"


def upgrade() -> None:
    op.drop_constraint(_RESTRICCION, "store_promotions", type_="unique")
    op.create_index(
        _INDICE,
        "store_promotions",
        ["store_id", "code"],
        unique=True,
        postgresql_where=sa.text("is_active"),
        sqlite_where=sa.text("is_active"),
    )


def downgrade() -> None:
    # En modo offline (`alembic downgrade --sql`) no hay conexion para contar:
    # se emite el DDL y el chequeo lo hace el propio ADD CONSTRAINT.
    repetidos = (
        0
        if context.is_offline_mode()
        else op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM ("
                "  SELECT store_id, code FROM store_promotions "
                "  GROUP BY store_id, code HAVING count(*) > 1"
                ") AS d"
            )
        )
        .scalar()
    )
    if repetidos:
        raise RuntimeError(
            f"store_promotions tiene {repetidos} codigo(s) reusados dentro de una "
            "misma tienda (una promocion activa y otra dada de baja con el mismo "
            "codigo). La restriccion vieja no los admite y esta migracion no "
            "decide cual conservar: resolverlos a mano y volver a correr el "
            "downgrade."
        )
    op.drop_index(_INDICE, table_name="store_promotions")
    op.create_unique_constraint(_RESTRICCION, "store_promotions", ["store_id", "code"])
