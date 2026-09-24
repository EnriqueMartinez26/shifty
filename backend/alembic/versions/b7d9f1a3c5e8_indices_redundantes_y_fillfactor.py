"""quitar indices redundantes y fillfactor 90 en appointments (F1-15, R7-06)

``appointments`` tenia 13 indices y ``n_tup_hot_upd = 0``: cada cambio de estado
reescribia todos los indices. Se quitan los que no agregan nada:

- Duplicados de la clave primaria, que creaba el modelo con
  ``primary_key=True, index=True``: ``ix_appointments_id``, ``ix_users_id``,
  ``ix_staff_id``, ``ix_schedules_id``, ``ix_appointment_blocks_id``.
- Prefijos de un compuesto que ya existe (el compuesto sirve para lo mismo,
  FK incluida): ``ix_appointments_store_id``, ``ix_store_schedules_store_id``,
  ``ix_otp_verifications_store_id``, ``ix_waitlist_entries_store_id``,
  ``ix_coupon_redemptions_coupon_id``. (``ix_notifications_store_id`` ya lo
  quito F1-14.)

``ix_staff_email`` e ``ix_appointments_service_id`` se quedan: sin uso en la
base local, se revisan con la prueba de carga.

``fillfactor = 90`` deja lugar en cada pagina para que un UPDATE que no toca
columnas indexadas sea HOT. Toma ``SHARE UPDATE EXCLUSIVE`` (no frena lecturas
ni escrituras) y rige para las paginas que se escriban desde ahora.

Los ``DROP`` van con ``CONCURRENTLY`` en ``autocommit_block``; el downgrade los
recrea igual (``DROP ... IF EXISTS`` antes, por un intento cortado).

Revision ID: b7d9f1a3c5e8
Revises: a6c8e0f2b4d7
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b7d9f1a3c5e8"
down_revision: Union[str, Sequence[str], None] = "a6c8e0f2b4d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REDUNDANTES = {
    "ix_appointments_id": "appointments (id)",
    "ix_users_id": "users (id)",
    "ix_staff_id": "staff (id)",
    "ix_schedules_id": "schedules (id)",
    "ix_appointment_blocks_id": "appointment_blocks (id)",
    "ix_appointments_store_id": "appointments (store_id)",
    "ix_store_schedules_store_id": "store_schedules (store_id)",
    "ix_otp_verifications_store_id": "otp_verifications (store_id)",
    "ix_waitlist_entries_store_id": "waitlist_entries (store_id)",
    "ix_coupon_redemptions_coupon_id": "coupon_redemptions (coupon_id)",
}


def upgrade() -> None:
    op.execute("ALTER TABLE appointments SET (fillfactor = 90)")
    with op.get_context().autocommit_block():
        for nombre in REDUNDANTES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for nombre, definicion in REDUNDANTES.items():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")
            op.execute(f"CREATE INDEX CONCURRENTLY {nombre} ON {definicion}")
    op.execute("ALTER TABLE appointments RESET (fillfactor)")
