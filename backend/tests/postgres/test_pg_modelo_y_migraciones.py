"""Los modelos y las migraciones no divergen mas de lo declarado (F1-15, R7-06).

2026-09-24, plan de rendimiento. ``appointments`` tenia 13 indices y 0 UPDATE
HOT: cada cambio de estado reescribia todos. Varios eran redundantes y los
creaba el propio modelo con ``index=True``: duplicados de la clave primaria
(``ix_*_id``) y prefijos de un compuesto que ya existe. Quitarlos solo en una
migracion no alcanza: el siguiente ``alembic revision --autogenerate`` los
volveria a proponer. Este test compara el modelo con la base migrada (lo que
haria ``alembic check``) y fija la deriva que YA existia antes de F1-15 como
techo: puede bajar, no subir. Un indice nuevo que viva solo en una migracion,
o un ``index=True`` que la migracion no crea, lo hace fallar.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg2
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, pool, text
from sqlalchemy.ext.asyncio import AsyncEngine

from core.model_registry import load_all_models
from core.models import Base
from tests.postgres.conftest import OWNER_URL, _sync_dsn

pytestmark = pytest.mark.postgres

# Deriva previa a F1-15 (2026-09-24): indices y restricciones que viven solo en
# las migraciones o solo en el modelo. Es deuda: al tocar uno de estos, se
# alinea y se BORRA de aca. No se agrega nada.
DERIVA_DECLARADA = {
    "remove_index:ix_budgets_store_id",
    "remove_table:budgets",
    "modify_nullable:appointments.ends_at",
    "remove_index:ix_appointments_store_staff_starts_at",
    "remove_index:ix_appointments_store_starts_at",
    "remove_index:ix_appointments_store_status_starts_at",
    "add_index:ix_appointments_ends_at",
    "remove_index:ix_coupon_redemptions_coupon_store",
    "remove_index:ix_customer_ledger_store_client",
    "add_index:ix_customer_ledger_client_id",
    "add_index:ix_customer_ledger_movement_type",
    "add_index:ix_customer_ledger_store_id",
    "remove_index:ix_notifications_store_created",
    "remove_index:ix_otp_store_phone_created",
    "remove_index:ix_outbox_pending",
    "remove_index:ix_store_schedules_store_day",
    "add_constraint:uq_store_day_schedule",
    "remove_index:uq_store_subscriptions_active_store",
    "remove_index:ix_webhook_inbox_pending",
}

# F1-15: redundantes que se quitan (base Y modelo).
REDUNDANTES = {
    # Duplican la clave primaria.
    "ix_appointments_id",
    "ix_users_id",
    "ix_staff_id",
    "ix_schedules_id",
    "ix_appointment_blocks_id",
    # Prefijo de un compuesto que ya existe.
    "ix_appointments_store_id",
    "ix_store_schedules_store_id",
    "ix_otp_verifications_store_id",
    "ix_waitlist_entries_store_id",
    "ix_coupon_redemptions_coupon_id",
}


def _nombre(diff: Any) -> str:
    if isinstance(diff, list):
        cambio = diff[0]
        return f"{cambio[0]}:{cambio[2]}.{cambio[3]}"
    objeto = diff[1]
    return f"{diff[0]}:{getattr(objeto, 'name', objeto)}"


def _deriva() -> Iterator[str]:
    assert OWNER_URL
    dsn = _sync_dsn(OWNER_URL)
    engine = create_engine(
        "postgresql+psycopg2://",
        creator=lambda: psycopg2.connect(dsn),
        poolclass=pool.NullPool,
    )
    load_all_models()
    try:
        with engine.connect() as conn:
            for diff in compare_metadata(
                MigrationContext.configure(conn), Base.metadata
            ):
                yield _nombre(diff)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_la_deriva_entre_modelo_y_migraciones_no_crece(
    owner_engine: AsyncEngine,
) -> None:
    deriva = set(_deriva())
    nueva = deriva - DERIVA_DECLARADA
    assert not nueva, (
        "el modelo y las migraciones divergen en algo nuevo: declarar el indice "
        f"en el modelo Y en una migracion (o quitarlo de los dos): {sorted(nueva)}"
    )
    resuelta = DERIVA_DECLARADA - deriva
    assert not resuelta, (
        f"deriva ya resuelta, borrarla de DERIVA_DECLARADA: {sorted(resuelta)}"
    )


@pytest.mark.asyncio
async def test_los_indices_redundantes_no_existen_y_appointments_deja_lugar_para_hot(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.connect() as conn:
        existentes = {
            fila[0]
            for fila in (
                await conn.execute(
                    text("select indexname from pg_indexes where schemaname = 'public'")
                )
            ).all()
        }
        opciones = (
            await conn.execute(
                text("select reloptions from pg_class where relname = 'appointments'")
            )
        ).scalar_one()
    assert not REDUNDANTES & existentes, sorted(REDUNDANTES & existentes)
    # Los que la revision dijo que se quedan hasta medir con carga real.
    assert {"ix_staff_email", "ix_appointments_service_id"} <= existentes
    assert "fillfactor=90" in (opciones or []), opciones
