"""app_role_timeouts

Defensa en profundidad para escala: acota en el rol de la app el tiempo de una
query, la espera por un lock y el tiempo ocioso dentro de una transaccion. Sin
esto, una query pesada, una contencion o una transaccion abandonada retienen una
conexion del pool hasta agotarlo. Valores conservadores para no cortar flujos
legitimos (el cobro sostiene brevemente un lock durante la llamada a Mercado
Pago). Aplican a las NUEVAS sesiones del rol.

Revision ID: c2e4f6a8b0d1
Revises: b1d3f5a7c9e0
Create Date: 2026-09-03 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c2e4f6a8b0d1"
down_revision: Union[str, Sequence[str], None] = "b1d3f5a7c9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "shifty_app"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER ROLE {APP_ROLE} SET statement_timeout = '30s'")
    op.execute(f"ALTER ROLE {APP_ROLE} SET lock_timeout = '5s'")
    op.execute(f"ALTER ROLE {APP_ROLE} SET idle_in_transaction_session_timeout = '60s'")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER ROLE {APP_ROLE} RESET statement_timeout")
    op.execute(f"ALTER ROLE {APP_ROLE} RESET lock_timeout")
    op.execute(f"ALTER ROLE {APP_ROLE} RESET idle_in_transaction_session_timeout")
