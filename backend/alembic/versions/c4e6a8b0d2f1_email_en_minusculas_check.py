"""users.email en minusculas: CHECK NOT VALID (F1-12, R7-01)

El login y el olvido de clave buscaban con ``lower(users.email) = :email``.
``lower`` no es leakproof: bajo RLS Postgres no puede usarlo como condicion de
indice y cada login recorria ``users`` entera (el olvido de clave es publico).
Todo camino de alta ya normaliza con ``normalize_email`` (regla 16); este
CHECK lleva esa garantia a la base para que las consultas comparen la columna
por igualdad y usen ``ix_users_email``.

Expand/contract: esta revision agrega el CHECK ``NOT VALID`` (lock breve, no
recorre la tabla); ``d5f7b9c1e3a2`` lo valida aparte con un lock que no frena
lecturas ni escrituras.

Si la base tiene emails con mayusculas, la migracion NO los normaliza (decision
16 del plan): se detiene con el conteo para que alguien decida, porque dos
filas pueden colapsar en la misma identidad.

Revision ID: c4e6a8b0d2f1
Revises: d1f3b5a7c9e2
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "c4e6a8b0d2f1"
down_revision: Union[str, Sequence[str], None] = "d1f3b5a7c9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # En modo offline (`alembic upgrade --sql`) no hay conexion para contar:
    # el VALIDATE de la revision siguiente hace el chequeo.
    con_mayusculas = (
        0
        if context.is_offline_mode()
        else op.get_bind()
        .execute(sa.text("SELECT count(*) FROM users WHERE email <> lower(email)"))
        .scalar()
    )
    if con_mayusculas:
        raise RuntimeError(
            f"users tiene {con_mayusculas} email(s) con mayusculas. Esta migracion "
            "no los normaliza: revisar esas filas (dos pueden ser la misma "
            "persona), pasarlas a minusculas a mano y volver a correr "
            "`alembic upgrade head`."
        )
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_email_lower "
        "CHECK (email = lower(email)) NOT VALID"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_email_lower")
