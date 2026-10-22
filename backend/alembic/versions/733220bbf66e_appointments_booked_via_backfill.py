"""appointments.booked_via: backfill de lo historico y VALIDATE del CHECK

Segunda mitad de ``c7cd51eba96c`` (S5, paquete antiabuso, 2026-10-22).

1. Backfill: ``booked_via = 'portal'`` donde ``terms_accepted_at IS NOT NULL``.
   Solo el portal escribe ``terms_accepted_at`` (la reserva publica y la
   oferta de la lista de espera que acepta el cliente); el panel lo deja NULL
   porque el personal no es el cliente dando su consentimiento (PV-09). El
   resto ya vale ``'panel'`` por el default de la columna. Un turno del
   portal que el panel reprogramo nace sin ``terms_accepted_at`` y queda
   ``panel``, igual que lo escribe el codigo nuevo (lo movio la tienda).

   Por lotes con clave por id (``LOTE`` filas por lectura) y, en Postgres, en
   ``autocommit_block``: cada UPDATE se confirma solo, asi que no hay un lock
   largo sobre ``appointments`` mientras el codigo viejo sigue sirviendo
   (patron ``b5d7f9a1c3e6``). RLS esta forzada en ``appointments``: el bypass
   se fija a nivel de sesion (en autocommit un ``set_config(..., true)``
   duraria una sola sentencia) y se apaga al final. Idempotente: una segunda
   corrida no encuentra nada que marcar. Informa la cantidad en el log de
   alembic.

2. ``VALIDATE CONSTRAINT ck_appointments_booked_via`` recorre la tabla con
   ``SHARE UPDATE EXCLUSIVE``: no frena lecturas ni escrituras de la app.
   Toda fila vale ``panel`` o ``portal``, asi que valida sin cambios.

El downgrade vuelve al esquema de la revision anterior: el CHECK sin validar.
Los datos no se tocan: ``portal`` ya era un valor valido ahi, y devolver todo
a ``panel`` borraria tambien el origen de las reservas que el codigo nuevo
escribio despues (el downgrade de ``c7cd51eba96c`` borra la columna entera).

Revision ID: 733220bbf66e
Revises: c7cd51eba96c
Create Date: 2026-10-22
"""

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "733220bbf66e"
down_revision: Union[str, Sequence[str], None] = "c7cd51eba96c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

LOTE = 500
CHECK_ORIGEN = "ck_appointments_booked_via"

appointments = sa.table(
    "appointments",
    sa.column("id", sa.String()),
    sa.column("terms_accepted_at", sa.DateTime(timezone=True)),
    sa.column("booked_via", sa.String()),
)


def marcar_portal(bind: sa.Connection, *, lote: int = LOTE) -> int:
    """Marca ``portal`` donde el cliente acepto los terminos, por lotes con
    clave por id; devuelve cuantas filas cambio."""
    cambiadas = 0
    ultimo = ""
    while True:
        ids = list(
            bind.execute(
                sa.select(appointments.c.id)
                .where(
                    appointments.c.terms_accepted_at.is_not(None),
                    appointments.c.booked_via == "panel",
                    appointments.c.id > ultimo,
                )
                .order_by(appointments.c.id)
                .limit(lote)
            ).scalars()
        )
        if not ids:
            return cambiadas
        bind.execute(
            sa.update(appointments)
            .where(appointments.c.id.in_(ids))
            .values(booked_via="portal")
        )
        cambiadas += len(ids)
        ultimo = ids[-1]


def _backfill() -> int:
    if op.get_bind().dialect.name != "postgresql":
        return marcar_portal(op.get_bind())
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        bind.execute(sa.text("SELECT set_config('app.is_global_admin', 'true', false)"))
        try:
            return marcar_portal(bind)
        finally:
            bind.execute(
                sa.text("SELECT set_config('app.is_global_admin', 'false', false)")
            )


def upgrade() -> None:
    # Offline (``--sql``) no hay filas que leer: el backfill es solo online.
    if not op.get_context().as_sql:
        cambiadas = _backfill()
        logger.info("appointments.booked_via = 'portal' en %s fila(s)", cambiadas)
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE appointments VALIDATE CONSTRAINT {CHECK_ORIGEN}")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE appointments DROP CONSTRAINT {CHECK_ORIGEN}")
    op.execute(
        f"ALTER TABLE appointments ADD CONSTRAINT {CHECK_ORIGEN} "
        "CHECK (booked_via IN ('portal', 'panel')) NOT VALID"
    )
