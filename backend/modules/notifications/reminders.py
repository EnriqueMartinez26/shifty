"""Etapas del recordatorio al cliente: 24 horas y 2 horas antes del turno.

Logica pura (sin base ni red) para que se pueda testear con fechas fijas.
La regla de cada etapa es una sola: un recordatorio se manda solo si la
reserva es anterior al momento del recordatorio. Quien reserva 23 horas antes
ya recibio el mail de reserva hace un rato y solo recibe el de 2 horas; quien
reserva 30 minutos antes no recibe ninguno.

El piso del de 24 horas (no mandarlo si faltan menos de dos horas) cubre el
caso de un job que estuvo caido: cuando vuelve, manda solo el de 2 horas en
vez de dos mails seguidos.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from core.utils import ensure_utc_aware


@dataclass(frozen=True)
class ReminderStage:
    name: str
    column: str
    lead: timedelta
    floor: timedelta


STAGE_24H = ReminderStage(
    name="24h",
    column="reminder_24h_sent_at",
    lead=timedelta(hours=24),
    floor=timedelta(hours=2),
)
STAGE_2H = ReminderStage(
    name="2h",
    column="reminder_2h_sent_at",
    lead=timedelta(hours=2),
    floor=timedelta(0),
)
STAGES: tuple[ReminderStage, ...] = (STAGE_24H, STAGE_2H)


def stage_is_due(
    stage: ReminderStage,
    *,
    starts_at: datetime,
    created_at: datetime | None,
    now: datetime,
    already_sent: bool,
) -> bool:
    if already_sent:
        return False
    starts_at = ensure_utc_aware(starts_at)
    now = ensure_utc_aware(now)
    remaining = starts_at - now
    if remaining <= stage.floor:
        return False
    reminder_at = starts_at - stage.lead
    if now < reminder_at:
        return False
    if created_at is not None and ensure_utc_aware(created_at) > reminder_at:
        return False
    return True


def due_stages(appointment: Any, now: datetime) -> list[ReminderStage]:
    """Etapas que corresponde mandar ahora para este turno, en orden."""
    return [
        stage
        for stage in STAGES
        if stage_is_due(
            stage,
            starts_at=appointment.starts_at,
            created_at=getattr(appointment, "created_at", None),
            now=now,
            already_sent=getattr(appointment, stage.column, None) is not None,
        )
    ]
