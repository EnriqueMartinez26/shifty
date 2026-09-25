"""email de cliente unico por tienda; el de quien inicia sesion, global (PV-01)

2026-09-25, auditoria de privacidad PV-01. ``users.email`` era unico en toda
la plataforma (``ix_users_email`` UNIQUE mas el funcional
``uq_users_email_lower``). Un cliente que reservaba en la tienda A no podia
reservar en la B con el mismo email (409), y ese 409 era un oraculo publico:
cualquiera sabia si un email existia en Shifty, fuera cliente de otra tienda o
cuenta de administrador.

Decision del dueno (2026-09-25): un cliente usa el mismo email en todas las
tiendas que quiera. Los clientes no inician sesion (portal por telefono +
OTP); el personal, los admins y el superadmin si, por email, y el suyo sigue
unico global. Queda:

- ``uq_users_client_email_per_store``: UNIQUE ``(store_id, email)`` WHERE
  ``role = 'client'``.
- ``uq_users_email_non_client``: UNIQUE ``(email)`` WHERE ``role <> 'client'``.
  El login y el olvido de clave buscan ``email = :x AND role <> 'client'``
  (``modules/auth/service.py::login_account_email``): a lo sumo UNA fila.
- ``ix_users_email`` pasa a indice comun: sigue sirviendo la igualdad del
  login bajo RLS (regla 16), pero ya no es unico.
- ``uq_users_email_lower`` (funcional, global) se retira: con
  ``ck_users_email_lower`` validado toda fila ya esta en minusculas, asi que
  los dos indices parciales sobre la columna valen sin importar mayusculas.
  Partirlo en dos funcionales seria repetir lo mismo con ``lower()``.

Todo con ``CONCURRENTLY`` dentro de ``autocommit_block`` y ``DROP INDEX
CONCURRENTLY IF EXISTS`` antes de cada ``CREATE`` (un intento cortado deja un
indice INVALID con el mismo nombre). El indice comun se crea con nombre
temporal y se renombra despues de quitar el unico: nunca hay un momento sin
indice sobre ``email``. El upgrade no necesita guarda de datos: lo que era
unico global ya cumple las dos restricciones nuevas.

Rollback sin migrar (docs/DEPLOY_RUNBOOK.md): el codigo anterior busca el
login por ``email`` sin filtrar el rol. Si mientras tanto un cliente dejo el
email de un profesional o admin, el login de esa cuenta con el codigo viejo
responde 500 (MultipleResultsFound) hasta volver a este release.

Downgrade real, con guarda: volver a la unicidad global exige que ningun email
este en dos filas (dos tiendas, o cliente y personal). Si las hay, se detiene
con el conteo: no borra ni elige por nadie.

Revision ID: 4b6d8f0a2c13
Revises: a3c5e7f9b1d2
Create Date: 2026-09-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "4b6d8f0a2c13"
down_revision: Union[str, Sequence[str], None] = "a3c5e7f9b1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NUEVOS = {
    "uq_users_client_email_per_store": (
        "CREATE UNIQUE INDEX CONCURRENTLY uq_users_client_email_per_store "
        "ON users (store_id, email) WHERE role = 'client'"
    ),
    "uq_users_email_non_client": (
        "CREATE UNIQUE INDEX CONCURRENTLY uq_users_email_non_client "
        "ON users (email) WHERE role <> 'client'"
    ),
}
TEMPORAL = "ix_users_email_swap"


def _crear(nombre: str, sentencia: str) -> None:
    op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")
    op.execute(sentencia)


def _reemplazar_ix_users_email(*, unico: bool) -> None:
    """``ix_users_email`` con o sin UNIQUE, sin dejar la columna sin indice."""
    tipo = "UNIQUE INDEX" if unico else "INDEX"
    _crear(TEMPORAL, f"CREATE {tipo} CONCURRENTLY {TEMPORAL} ON users (email)")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_users_email")
    op.execute(f"ALTER INDEX {TEMPORAL} RENAME TO ix_users_email")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for nombre, sentencia in NUEVOS.items():
            _crear(nombre, sentencia)
        _reemplazar_ix_users_email(unico=False)
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_users_email_lower")


def _emails_repetidos() -> int:
    # En modo offline (`alembic downgrade --sql`) no hay conexion para contar:
    # se emite el DDL y el chequeo lo hace el propio CREATE UNIQUE INDEX.
    if context.is_offline_mode():
        return 0
    return int(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM ("
                "  SELECT email FROM users GROUP BY email HAVING count(*) > 1"
                ") AS d"
            )
        )
        .scalar()
        or 0
    )


def downgrade() -> None:
    repetidos = _emails_repetidos()
    if repetidos:
        raise RuntimeError(
            f"users tiene {repetidos} email(s) en mas de una fila (clientes de "
            "distintas tiendas, o un cliente y una cuenta del personal). La "
            "unicidad global no se puede restaurar sin elegir por alguien: "
            "unificar o cambiar esas filas a mano y volver a correr el downgrade."
        )
    with op.get_context().autocommit_block():
        _crear(
            "uq_users_email_lower",
            "CREATE UNIQUE INDEX CONCURRENTLY uq_users_email_lower "
            "ON users (lower(email))",
        )
        _reemplazar_ix_users_email(unico=True)
        for nombre in NUEVOS:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")
