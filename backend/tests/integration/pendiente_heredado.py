"""Turno ``pending`` de una reserva publica sin cobro de antes del 2026-10-20.

Desde la decision de Mateo del 2026-10-20 una reserva publica sin cobro nace
``confirmed`` y sin retencion. Los ``pending`` que ya existian siguen en
produccion (no hubo migracion de datos) y su camino sigue vivo: liberarlos,
vencerlos a la hora del turno, reprogramarlos conservando la retencion. El
alta ya no los crea, asi que los tests de ese camino los fijan con esto.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment, AppointmentStatus


async def como_pendiente_heredado(session: AsyncSession, turno: str) -> None:
    """Deja el turno ``pending`` retenido hasta su inicio, como nacia antes.

    Escritura directa: el grafo no tiene ``confirmed -> pending``.
    """
    session.expire_all()
    inicio = await session.scalar(
        select(Appointment.starts_at).where(Appointment.id == turno)
    )
    assert inicio is not None
    await session.execute(
        update(Appointment)
        .where(Appointment.id == turno)
        .values(status=AppointmentStatus.PENDING.value, expires_at=inicio)
    )
    await session.commit()
    session.expire_all()
