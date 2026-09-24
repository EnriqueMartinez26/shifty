"""el OTP registra a que email se despacho el codigo

``otp_verifications.email`` guarda la direccion a la que se mando el codigo.
Sin ella, ``verified_at`` solo probaba "alguien acerto un codigo de este
telefono" y el que pedia el codigo elegia el buzon: saber un telefono ajeno y
poner el email propio alcanzaba para listar, cancelar o reprogramar los turnos
de esa persona (`/public/otp/request` es publico).

La columna es NULLABLE por las filas anteriores a esta migracion, y NULL se
trata como FAIL CLOSED en el codigo (``_matches_verified_email`` compara por
igualdad -- ``NULL = 'x'`` es NULL, no verdadero -- y cuando pregunta "contra
algun email" exige ``IS NOT NULL``): una verificacion vieja no otorga ningun
privilegio. No se pone default a proposito: cualquier valor inventado podria
coincidir por accidente con el email de una ficha.

RIESGOS DE DESPLIEGUE
---------------------
1. ORDEN DE ROLLBACK. Correr ``alembic downgrade -1`` con el codigo nuevo YA
   desplegado rompe TODO ``/public/otp/request``: el ORM
   (``modules/otp/model.py``) mapea ``OtpVerification.email`` y el INSERT
   nombra una columna que ya no existe. El orden seguro es al reves: primero
   volver atras la APP, despues la migracion.
2. VERIFICACIONES EN VUELO. Las verificaciones de los 30 minutos previos al
   deploy quedan con ``email = NULL`` y, por el fail closed de arriba, no
   habilitan nada: esos clientes tienen que volver a pedir el codigo. Es una
   ventana acotada y auto-resolutiva de 30 minutos (la de
   ``window_minutes``), no un estado que requiera backfill -- y no se puede
   backfillear: no hay registro de a que buzon fue el codigo.

Revision ID: b8d1c4f70a25
Revises: d1f3b5a7c9e2
Create Date: 2026-09-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d1c4f70a25"
down_revision: Union[str, Sequence[str], None] = "c9e1f3a5b7d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "otp_verifications",
        sa.Column("email", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("otp_verifications", "email")
