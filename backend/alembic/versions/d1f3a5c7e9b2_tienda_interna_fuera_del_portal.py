"""stores.is_internal: la tienda del SuperAdmin no existe para el portal

``scripts/bootstrap_superadmin.py`` crea una tienda (slug
``SUPERADMIN_STORE_SLUG``, por defecto ``shifty-internal``) solo para alojar
las cuentas SuperAdmin. El portal publico la resolvia como cualquier otra:
``GET /public/stores/shifty-internal`` respondia 200. Con esta columna el
portal la trata como inexistente (``public_api/repository.py``) y el panel
del SuperAdmin la sigue listando.

Expand puro (docs/DEPLOY_RUNBOOK.md, seccion 5): columna nueva NOT NULL con
default constante, que en Postgres 11+ no reescribe la tabla (solo catalogo).
El codigo anterior no la lee, asi que la ventana del deploy y el rollback sin
migrar no cambian nada.

Marca la tienda que ya existe con el slug por defecto del bootstrap: es la
unica forma de cubrir un despliegue que ya la tiene. Una tienda creada antes
con un ``SUPERADMIN_STORE_SLUG`` propio se marca a mano: el bootstrap no marca
una tienda que ya existe, porque con el slug mal puesto podria ser una real.

El downgrade borra la columna: la tienda interna vuelve a ser publica.

Revision ID: d1f3a5c7e9b2
Revises: c7e9a1b3d5f8
Create Date: 2026-10-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1f3a5c7e9b2"
down_revision: Union[str, Sequence[str], None] = "c7e9a1b3d5f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SLUG_POR_DEFECTO_DEL_BOOTSTRAP = "shifty-internal"


def upgrade() -> None:
    op.add_column(
        "stores",
        sa.Column(
            "is_internal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute(
        sa.text("UPDATE stores SET is_internal = true WHERE slug = :slug").bindparams(
            slug=SLUG_POR_DEFECTO_DEL_BOOTSTRAP
        )
    )


def downgrade() -> None:
    op.drop_column("stores", "is_internal")
