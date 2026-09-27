"""appointments: tope de duracion de un dia, CHECK NOT VALID (F1-13, R7-02)

Toda consulta de solapamiento era ``starts_at < fin AND ends_at > inicio``, que
sobre un indice que empieza por ``starts_at`` solo acota por arriba: recorria
toda la historia del profesional, tambien bajo el ``FOR UPDATE`` del alta. La
cota inferior ``starts_at > inicio - 1 dia`` es correcta solo si ningun turno
dura mas de un dia; este CHECK lo garantiza en la base (decision 15 del plan).
El tope del producto es 480 minutos (``services/schemas.py``): el de la base es
holgado a proposito y no cambia nada de lo que hoy se puede reservar.

Expand/contract: ``NOT VALID`` aca (lock breve, no recorre la tabla) y
``VALIDATE`` en ``f0a2c4e6b8d1``. Si ya hay turnos de mas de un dia, la
migracion se detiene con el conteo: no recorta ni borra turnos por nadie.

Revision ID: e9f1b3d5a7c0
Revises: d5f7b9c1e3a2
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "e9f1b3d5a7c0"
down_revision: Union[str, Sequence[str], None] = "d5f7b9c1e3a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # En modo offline no hay conexion para contar: el VALIDATE de la revision
    # siguiente hace el chequeo.
    largos = (
        0
        if context.is_offline_mode()
        else op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM appointments "
                "WHERE ends_at > starts_at + interval '1 day'"
            )
        )
        .scalar()
    )
    if largos:
        raise RuntimeError(
            f"appointments tiene {largos} turno(s) de mas de un dia. Esta "
            "migracion no los corrige: revisarlos a mano y volver a correr "
            "`alembic upgrade head`."
        )
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT ck_appointments_max_span "
        "CHECK (ends_at <= starts_at + interval '1 day') NOT VALID"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS ck_appointments_max_span"
    )
