"""CHECK de la terna de sena en services (modo, tipo, monto)

Hasta aca la terna se validaba SOLO en la entrada (Pydantic). Lo que toca
dinero se garantiza con algo determinista en Postgres:

- ``ck_services_deposit_amount_presente``: con ``deposit_mode`` distinto de
  ``none`` y ``deposit_type`` distinto de ``full``, el monto existe y es
  mayor a 0. Sin esto una fila con ``required`` sin monto reservaba sin
  cobrar y nadie la enumeraba.
- ``ck_services_deposit_percent_max``: un porcentaje de sena no supera 100.
  Una fila con ``percent`` = 500 cobraba 5 veces el precio por adelantado.

Es el mismo criterio que ``modules.services.schemas.deposit_policy_error``,
aplicado a las filas que no pasan por el schema: carga directa, migraciones
y dos PATCH concurrentes que validan cada uno contra el snapshot que leyo
sin lock y se pisan.

Si la base ya tiene filas que violan la terna, la migracion NO las corrige:
se detiene con el conteo para que el dueno decida cada caso (mismo patrono
que ``c9e1f3a5b7d9`` con los telefonos repetidos).

Revision ID: d1f3b5a7c9e2
Revises: c5e7a9b1d3f4
Create Date: 2026-09-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "d1f3b5a7c9e2"
down_revision: Union[str, Sequence[str], None] = "c5e7a9b1d3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MONTO_PRESENTE = (
    "deposit_mode = 'none' OR deposit_type = 'full' "
    "OR (deposit_amount IS NOT NULL AND deposit_amount > 0)"
)
_PORCENTAJE_MAX = (
    "deposit_type <> 'percent' OR deposit_amount IS NULL OR deposit_amount <= 100"
)


def _contar_invalidas() -> int:
    """Filas que violan la terna. 0 en modo offline: no hay conexion."""
    if context.is_offline_mode():
        return 0
    resultado = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM services "
                f"WHERE NOT ({_MONTO_PRESENTE}) OR NOT ({_PORCENTAJE_MAX})"
            )
        )
        .scalar()
    )
    return int(resultado or 0)


def upgrade() -> None:
    invalidas = _contar_invalidas()
    if invalidas:
        raise RuntimeError(
            f"services tiene {invalidas} fila(s) con una terna de sena invalida "
            "(sena obligatoria sin monto, o porcentaje mayor a 100). Esta "
            "migracion no decide cuanto cobra cada servicio: corregir esas "
            "filas a mano y volver a correr `alembic upgrade head`."
        )
    op.create_check_constraint(
        "ck_services_deposit_amount_presente", "services", sa.text(_MONTO_PRESENTE)
    )
    op.create_check_constraint(
        "ck_services_deposit_percent_max", "services", sa.text(_PORCENTAJE_MAX)
    )


def downgrade() -> None:
    op.drop_constraint("ck_services_deposit_percent_max", "services", type_="check")
    op.drop_constraint("ck_services_deposit_amount_presente", "services", type_="check")
