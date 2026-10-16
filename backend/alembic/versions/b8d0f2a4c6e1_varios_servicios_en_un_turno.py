"""appointments.extra_services_*: varios servicios del mismo profesional en un turno

Decision de Mateo (2026-10-16; pendiente de OK del dueno en docs/DECISIONES.md):
un profesional puede hacer varios servicios en UN turno (hasta 3 en total, con
una duracion total de hasta 480 minutos). ``appointments.service_id`` sigue
siendo el principal (el primero elegido); el turno congela los demas:

- ``extra_services_snapshot``: JSON nullable, sin default. Lista de
  ``{service_id, public_id, name, duration_minutes, price}`` (precio como
  texto). NULL en todo turno de un solo servicio.
- ``extra_services_amount``: la suma SIN descuento de esos precios. NOT NULL con
  default constante, que en Postgres 11+ no reescribe la tabla (solo
  catalogo).

``duration_minutes`` y ``ends_at`` ya son el total (la exclusion GiST cubre el
rango entero) y ``price_amount`` ya es el total congelado: no cambian de
significado.

Expand puro (docs/DEPLOY_RUNBOOK.md, seccion 5):

- ``ck_appointments_extra_services_amount`` (``extra_services_amount >= 0``)
  se agrega ``NOT VALID`` (lock breve, no recorre la tabla); ``c9e1a3b5d7f2``
  lo valida aparte, con un lock que no frena lecturas ni escrituras (patron
  ``e2a4c6e8f0b1`` + ``f3b5d7f9a1c2``).

El codigo anterior no lee nada de esto: la ventana del deploy (codigo viejo
sobre el esquema nuevo) y el rollback sin migrar siguen sirviendo. Riesgo
conocido del rollback: un turno de varios servicios que el codigo viejo
reprograme nace con la duracion del servicio principal solo (el viejo no sabe
de los extras). Antes de un rollback se apaga el flag ``multi_service_booking``
de cada tienda; los turnos ya tomados conservan su rango y su precio.

El downgrade borra las columnas: se pierde el detalle de los servicios extra de
los turnos que los eligieron (su total queda en ``price_amount`` y su rango en
``starts_at``/``ends_at``).

Revision ID: b8d0f2a4c6e1
Revises: f3b5d7f9a1c2
Create Date: 2026-10-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d0f2a4c6e1"
down_revision: Union[str, Sequence[str], None] = "f3b5d7f9a1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK_TURNO = "ck_appointments_extra_services_amount"


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column(
            "extra_services_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "appointments",
        sa.Column("extra_services_snapshot", sa.JSON(), nullable=True),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"ALTER TABLE appointments ADD CONSTRAINT {CHECK_TURNO} "
        "CHECK (extra_services_amount >= 0) NOT VALID"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"ALTER TABLE appointments DROP CONSTRAINT IF EXISTS {CHECK_TURNO}")
    op.drop_column("appointments", "extra_services_snapshot")
    op.drop_column("appointments", "extra_services_amount")
