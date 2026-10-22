"""appointments.booked_via: origen de la reserva (portal o panel)

Paquete antiabuso (S5, 2026-10-22; pedido de Mateo, pendiente de OK del
dueno): la tienda tiene que poder ver y limpiar las reservas que entraron por
el portal publico (``GET /appointments/recent-portal`` y
``POST /appointments/bulk-cancel``). El turno no guardaba de donde vino.

- ``booked_via``: ``varchar(20)`` NOT NULL con default constante ``'panel'``,
  que en Postgres 11+ no reescribe la tabla (solo catalogo). Valores
  ``portal`` | ``panel``.
- ``ck_appointments_booked_via`` (``booked_via IN ('portal', 'panel')``) se
  agrega ``NOT VALID`` (lock breve, no recorre la tabla); ``733220bbf66e``
  marca ``portal`` en lo historico y lo valida aparte (patron
  ``b8d0f2a4c6e1`` + ``c9e1a3b5d7f2``).

No se guarda IP ni user agent: la politica de privacidad no los cubre.

Expand puro (docs/DEPLOY_RUNBOOK.md, seccion 5): el codigo anterior no lee la
columna y sus INSERT toman el default, asi que la ventana del deploy (codigo
viejo sobre el esquema nuevo) y el rollback sin migrar siguen sirviendo. Lo
que se sabe de esa ventana: una reserva del portal que el codigo viejo
escriba despues del backfill queda ``panel`` (no aparece en "Reservas
recientes del portal"; se cancela igual desde la agenda).

El downgrade borra la columna: se pierde el origen de cada turno (el de los
historicos se puede volver a derivar de ``terms_accepted_at``).

Revision ID: c7cd51eba96c
Revises: a7c9e1b3d5f7
Create Date: 2026-10-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7cd51eba96c"
down_revision: Union[str, Sequence[str], None] = "a7c9e1b3d5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK_ORIGEN = "ck_appointments_booked_via"


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column(
            "booked_via",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'panel'"),
        ),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"ALTER TABLE appointments ADD CONSTRAINT {CHECK_ORIGEN} "
        "CHECK (booked_via IN ('portal', 'panel')) NOT VALID"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"ALTER TABLE appointments DROP CONSTRAINT IF EXISTS {CHECK_ORIGEN}")
    op.drop_column("appointments", "booked_via")
