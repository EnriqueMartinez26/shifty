"""payment_gateway_configs.connection_broken_at: la conexion de MP rota

Issue #279 (2026-11-02): cuando Mercado Pago rechaza renovar el token OAuth
de una tienda, la conexion queda marcada con el instante del rechazo hasta
que la tienda reconecta. ``gateway_has_usable_token`` la da por no usable y
la sena obligatoria pasa a WhatsApp si la tienda lo tiene.

Solo agrega (expand): columna nullable, sin default ni backfill, asi que el
``ALTER TABLE`` no reescribe la tabla y el codigo viejo la ignora. Las filas
existentes quedan en NULL: ninguna conexion arranca rota.

El downgrade la borra: se pierde la marca, y una conexion rota vuelve a
verse como conectada (el comportamiento de antes de esta revision).

Revision ID: a9c1e3f5b7d9
Revises: 733220bbf66e
Create Date: 2026-11-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9c1e3f5b7d9"
down_revision: Union[str, Sequence[str], None] = "733220bbf66e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_gateway_configs",
        sa.Column("connection_broken_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payment_gateway_configs", "connection_broken_at")
