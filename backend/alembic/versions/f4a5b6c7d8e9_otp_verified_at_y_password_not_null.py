"""separar verificacion OTP de invalidacion y blindar hashed_password

Revision ID: f4a5b6c7d8e9
Revises: e2f3a4b5c6d7
Create Date: 2026-09-01 12:00:00.000000

Dos arreglos de seguridad:

- ``otp_verifications.verified_at``: hasta ahora "verificado" se infería de
  ``consumed_at``, pero ese campo también se setea al invalidar códigos viejos
  cuando se emite uno nuevo. Resultado: pedir dos códigos seguidos marcaba el
  teléfono como verificado sin conocer ningún código, abriendo la autogestión
  pública de turnos. La prueba de posesión ahora tiene su propia columna.

- ``users.hashed_password`` vuelve a NOT NULL: una fila con hash NULL rompía el
  login con 500 (oráculo de enumeración y bypass del timing constante). Las
  filas NULL existentes se rellenan con un hash centinela imposible de acertar.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Un hash bcrypt sintacticamente valido cuya preimagen nadie conoce (generado
# de un secreto aleatorio descartado). Sirve solo para que la columna pueda ser
# NOT NULL sin habilitar el login de esas cuentas.
_SENTINEL_HASH = "$2b$12$C7yUKO7oQMoRuiSHs5C1V.gJv9L3f0eOnab3B1S/1lQ2S9jZbTf9K"


def upgrade() -> None:
    op.add_column(
        "otp_verifications",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_otp_verifications_verified_at",
        "otp_verifications",
        ["verified_at"],
    )

    op.execute(
        sa.text(
            "UPDATE users SET hashed_password = :sentinel WHERE hashed_password IS NULL"
        ).bindparams(sentinel=_SENTINEL_HASH)
    )
    op.alter_column(
        "users",
        "hashed_password",
        existing_type=sa.String(length=255),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "hashed_password",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.drop_index("ix_otp_verifications_verified_at", table_name="otp_verifications")
    op.drop_column("otp_verifications", "verified_at")
