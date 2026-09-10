"""Evento "se libero un cupo" para la lista de espera.

Se publica en la MISMA transaccion que libera el cupo (outbox transaccional),
en los seis caminos que lo hacen (cancelar, liberar, reprogramar, cancelar y
reprogramar del cliente, vencimiento de senas impagas) y al borrar un
bloqueo. El consumidor vive en ``modules.waitlist.offers``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import ensure_utc_aware
from modules.payments.model import JsonValue, OutboxMessage

EVENT_SLOT_RELEASED = "appointment.slot_released"


def slot_released_payload(
    *,
    staff_id: str,
    starts_at: datetime,
    ends_at: datetime,
    reason: str,
    service_id: str | None = None,
    appointment_id: str | None = None,
) -> dict[str, JsonValue]:
    return {
        "staff_id": staff_id,
        "service_id": service_id,
        "appointment_id": appointment_id,
        "starts_at": ensure_utc_aware(starts_at).isoformat(),
        "ends_at": ensure_utc_aware(ends_at).isoformat(),
        "reason": reason,
    }


def publish_slot_released(
    db: AsyncSession,
    *,
    store_id: str,
    staff_id: str,
    starts_at: datetime,
    ends_at: datetime,
    reason: str,
    service_id: str | None = None,
    appointment_id: str | None = None,
) -> None:
    """Para los caminos que trabajan con la sesion cruda (sin Unit of Work)."""
    db.add(
        OutboxMessage(
            store_id=store_id,
            event_type=EVENT_SLOT_RELEASED,
            payload=slot_released_payload(
                staff_id=staff_id,
                starts_at=starts_at,
                ends_at=ends_at,
                reason=reason,
                service_id=service_id,
                appointment_id=appointment_id,
            ),
        )
    )
