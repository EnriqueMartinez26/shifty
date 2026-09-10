"""ciclo de vida de la suscripcion: CHECK de estados, nombre del plan y aviso

El estado era texto libre (el front ofrecia "trialing", que el backend no
conocia). Se normalizan las filas existentes a los cuatro estados del
grafo (modules/billing/subscription_rules.py) y se agrega el CHECK. El
nombre del plan se copia a la suscripcion porque la tabla de planes es solo
para superadmin en RLS y el dueno necesita verlo. ``expiry_warning_sent_at``
hace idempotente el aviso de vencimiento (uno por periodo).

Revision ID: b7d9f1a3c5e7
Revises: a6c8e0f2b4d6
Create Date: 2026-09-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d9f1a3c5e7"
down_revision: Union[str, Sequence[str], None] = "a6c8e0f2b4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ESTADOS = "('active', 'past_due', 'suspended', 'cancelled')"


def upgrade() -> None:
    op.add_column(
        "store_subscriptions",
        sa.Column("plan_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "store_subscriptions",
        sa.Column("expiry_warning_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE store_subscriptions SET plan_name = plans.name "
        "FROM plans WHERE plans.id = store_subscriptions.plan_id"
        if op.get_bind().dialect.name == "postgresql"
        else "UPDATE store_subscriptions SET plan_name = "
        "(SELECT name FROM plans WHERE plans.id = store_subscriptions.plan_id)"
    )
    # "trialing" y cualquier valor desconocido pasan a activa: nunca fueron
    # estados del sistema, solo texto.
    op.execute(
        "UPDATE store_subscriptions SET status = 'active' "
        f"WHERE status NOT IN {ESTADOS}"
    )
    op.create_check_constraint(
        "ck_store_subscriptions_status", "store_subscriptions", f"status IN {ESTADOS}"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_store_subscriptions_status", "store_subscriptions", type_="check"
    )
    op.drop_column("store_subscriptions", "expiry_warning_sent_at")
    op.drop_column("store_subscriptions", "plan_name")
