"""guardas de datos del solapamiento y tope de duracion del servicio (F1-13)

La cota inferior del solapamiento de F1-13 da por ciertas dos cosas que hasta
ahora sostenia solo el codigo:

1. Ningun turno dura mas de un dia (``ck_appointments_max_span``). La duracion
   sale del servicio y su tope del producto (``le=480``) vive solo en Pydantic:
   un servicio de mas de 1440 minutos hacia fallar cada reserva contra el CHECK
   del turno. ``ck_services_duration_max`` frena el dato donde nace: NOT VALID
   aca y ``VALIDATE`` en ``d4e6f8a0b2c5`` (expand/contract).
2. Un turno o un bloqueo tiene la MISMA tienda que su profesional. Las lecturas
   bajo el lock filtran por la tienda del profesional: una fila con otra
   ``store_id`` quedaria invisible para el choque (doble reserva posible).

Si hay filas que no cumplen, la migracion NO las corrige: se detiene con el
conteo de cada caso para que alguien decida (mismo criterio que
``c4e6a8b0d2f1`` y ``e9f1b3d5a7c0``). ``docs/DEPLOY_RUNBOOK.md`` tiene las
consultas para correrlas antes del deploy.

Revision ID: c3d5e7f9a1b4
Revises: b2c4e6a8d0f3
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "c3d5e7f9a1b4"
down_revision: Union[str, Sequence[str], None] = "b2c4e6a8d0f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHEQUEOS = (
    (
        "SELECT count(*) FROM services WHERE duration_minutes > 1440",
        "servicio(s) de mas de 1440 minutos",
    ),
    (
        "SELECT count(*) FROM appointment_blocks b JOIN staff s ON s.id = b.staff_id "
        "WHERE b.store_id <> s.store_id",
        "bloqueo(s) con otra tienda que su profesional",
    ),
    (
        "SELECT count(*) FROM appointments a JOIN staff s ON s.id = a.staff_id "
        "WHERE a.store_id <> s.store_id",
        "turno(s) con otra tienda que su profesional",
    ),
)


def _problemas() -> list[str]:
    # En modo offline no hay conexion para contar: el VALIDATE de la revision
    # siguiente hace el chequeo de la duracion.
    if context.is_offline_mode():
        return []
    bind = op.get_bind()
    problemas = []
    for consulta, descripcion in CHEQUEOS:
        cuantos = bind.execute(sa.text(consulta)).scalar()
        if cuantos:
            problemas.append(f"{cuantos} {descripcion}")
    return problemas


def upgrade() -> None:
    problemas = _problemas()
    if problemas:
        raise RuntimeError(
            "Datos que rompen el supuesto del solapamiento: "
            + "; ".join(problemas)
            + ". Esta migracion no los corrige: revisarlos a mano y volver a "
            "correr `alembic upgrade head`."
        )
    op.execute(
        "ALTER TABLE services ADD CONSTRAINT ck_services_duration_max "
        "CHECK (duration_minutes <= 1440) NOT VALID"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE services DROP CONSTRAINT IF EXISTS ck_services_duration_max"
    )
