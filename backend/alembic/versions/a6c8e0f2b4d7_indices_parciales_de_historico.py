"""indices parciales para las consultas que recorrian historico (F1-14)

R3-01 / R3-02 / R7-05 / R7-08 del plan de rendimiento:

- ``ix_appointments_hold_expiry``: el job de vencimiento (cada minuto) busca
  retenciones vivas vencidas. ``expires_at`` nunca se limpia, asi que el indice
  plano ``ix_appointments_expires_at`` barria todas las retenciones viejas ya
  confirmadas, completadas o vencidas. El parcial solo tiene las vivas.
- ``ix_outbox_expire_claims``: el retome de reclamos de
  ``payment.preference.expire`` con lease vencido (cada minuto) caia en
  ``ix_outbox_messages_event_type``, todo el historico del evento. El parcial
  solo tiene las filas reclamadas.
- ``ix_notifications_store_unread``: el contador de no leidas (cada 60 s por
  usuario del panel) recorria todas las notificaciones de la tienda. El parcial
  solo tiene las no leidas y reemplaza a ``ix_notifications_store_id`` (prefijo
  de ``ix_notifications_store_created``) y ``ix_notifications_read_at`` (sin
  uso), que se quitan.

Todo con ``CONCURRENTLY`` dentro de ``autocommit_block`` (sin el lock que
frena escrituras) y ``DROP INDEX CONCURRENTLY IF EXISTS`` antes de cada
``CREATE``: un intento cortado deja un indice INVALID con el mismo nombre. Los
predicados son los literales de las consultas (``payments/jobs.py``,
``notifications/repository.py``); si cambian, el indice deja de servir y
``tests/postgres/test_pg_indices_parciales.py`` falla.

Revision ID: a6c8e0f2b4d7
Revises: a1b3d5f7c9e2
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a6c8e0f2b4d7"
down_revision: Union[str, Sequence[str], None] = "a1b3d5f7c9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NUEVOS = {
    "ix_appointments_hold_expiry": (
        "appointments (expires_at) "
        "WHERE status IN ('pending', 'pending_payment') AND expires_at IS NOT NULL"
    ),
    "ix_outbox_expire_claims": (
        "outbox_messages (processed_at) "
        "WHERE error = 'claimed:payment.preference.expire'"
    ),
    "ix_notifications_store_unread": "notifications (store_id) WHERE read_at IS NULL",
}
REEMPLAZADOS = {
    "ix_notifications_store_id": "notifications (store_id)",
    "ix_notifications_read_at": "notifications (read_at)",
}


def _crear(indices: dict[str, str]) -> None:
    for nombre, definicion in indices.items():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")
        op.execute(f"CREATE INDEX CONCURRENTLY {nombre} ON {definicion}")


def _quitar(indices: dict[str, str]) -> None:
    for nombre in indices:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        _crear(NUEVOS)
        _quitar(REEMPLAZADOS)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        _crear(REEMPLAZADOS)
        _quitar(NUEVOS)
