"""Cancelar desde el panel un turno ya cancelado es un conflicto, no un no-op.

Decision del coordinador sobre perf/f4-pay (2026-09-25, #4 del reporte),
CLAUDE.md §4 ("1 exito, N-1 conflictos"). Sintoma: ``PATCH
/appointments/{id}/cancel`` sobre un turno ya cancelado respondia 200
(``apply_status_transition`` deja pasar el mismo estado) y volvia a publicar
``appointment.slot_released`` y a escribir la auditoria: la lista de espera
recibia dos veces el mismo cupo y la rafaga daba N exitos.

Ahora la segunda cancelacion responde 409 ``APPOINTMENT_ALREADY_CANCELLED``
sin publicar nada ni auditar. Contrato para el front: un doble click recibe
409.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.audit.model import AuditAction, AuditLog
from modules.payments.model import OutboxMessage
from modules.waitlist.events import EVENT_SLOT_RELEASED
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import _tienda
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_link_del_panel_solo_turnos_vivos import _confirmado


async def _contar(session: AsyncSession, turno: str) -> tuple[int, int]:
    session.expire_all()
    liberados = [
        m
        for m in (
            await session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == EVENT_SLOT_RELEASED
                )
            )
        ).scalars()
        if m.payload.get("appointment_id") == turno
    ]
    auditorias = (
        await session.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.resource_id == turno,
                AuditLog.action == AuditAction.STATUS_CHANGE.value,
            )
        )
    ).scalar_one()
    return len(liberados), int(auditorias)


@pytest.mark.asyncio
async def test_la_segunda_cancelacion_es_409_y_no_republica(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "cancela-dos-veces", sena=False)
    turno = await _confirmado(client, t, 13)

    primera = await client.patch(
        f"/appointments/{turno}/cancel", headers=auth_headers(t.admin)
    )
    despues_de_la_primera = await _contar(test_session, turno)
    segunda = await client.patch(
        f"/appointments/{turno}/cancel", headers=auth_headers(t.admin)
    )

    assert primera.status_code == 200, primera.text
    assert despues_de_la_primera == (1, 1)
    assert segunda.status_code == 409, segunda.text
    assert segunda.json()["error_code"] == "APPOINTMENT_ALREADY_CANCELLED"
    assert await _contar(test_session, turno) == (1, 1)
