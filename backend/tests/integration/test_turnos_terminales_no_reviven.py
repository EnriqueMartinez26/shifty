"""Un turno terminal no se reprograma ni se vuelve a cancelar.

Revision de perf/f4-pay (2026-09-25, #2). Sintoma: reprogramar copiaba el
turno y cancelaba el original con ``apply_status_transition``, que deja pasar
el mismo estado: un turno que el personal ya habia cancelado se podia
"reprogramar" desde el portal (o desde el panel) y volvia a la vida. Y
cancelar dos veces desde el portal respondia 200 las dos, republicando el
cupo liberado y el aviso al dueno.

Ahora:
- reprogramar (portal y panel) un turno terminal (``cancelled``, ``expired``,
  ``completed``, ``absent``) es 409 ``APPOINTMENT_NOT_ACTIVE``, sin turno nuevo.
- cancelar desde el portal un turno ya cancelado es 409
  ``APPOINTMENT_ALREADY_CANCELLED`` (el mismo codigo que el panel), bajo el
  lock, sin republicar ``appointment.slot_released`` ni avisar otra vez.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.notifications.model import NotificationType
from modules.payments.model import OutboxMessage
from modules.waitlist.events import EVENT_SLOT_RELEASED
from tests.integration.test_autogestion_permisos_por_estado import _turno_en_estado
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import _tienda
from tests.integration.test_caracterizacion_autogestion import TELEFONO, _con_turno
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_link_del_panel_solo_turnos_vivos import _confirmado

TERMINALES = ["cancelled", "expired", "completed", "absent"]


async def _turnos(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(select(func.count()).select_from(Appointment))
        ).scalar_one()
    )


async def _eventos(session: AsyncSession, tipo: str, turno: str) -> int:
    session.expire_all()
    filas = (
        await session.execute(
            select(OutboxMessage).where(OutboxMessage.event_type == tipo)
        )
    ).scalars()
    return sum(1 for f in filas if f.payload.get("appointment_id") == turno)


@pytest.mark.asyncio
@pytest.mark.parametrize("estado", TERMINALES)
async def test_el_cliente_no_reprograma_un_turno_terminal(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    estado: str,
) -> None:
    t, base = await _con_turno(client, monkeypatch, f"terminal-portal-{estado}")
    turno = await _turno_en_estado(test_session, base, estado)
    antes = await _turnos(test_session)

    res = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (t.slot + timedelta(hours=2)).isoformat(),
            "idempotency_key": f"terminal-portal-{estado}-1",
        },
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "APPOINTMENT_NOT_ACTIVE"
    assert await _turnos(test_session) == antes


@pytest.mark.asyncio
@pytest.mark.parametrize("estado", TERMINALES)
async def test_el_panel_no_reprograma_un_turno_terminal(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    estado: str,
) -> None:
    t = await _tienda(client, monkeypatch, f"terminal-panel-{estado}", sena=False)
    turno = await _confirmado(client, t, 13)
    await test_session.execute(
        update(Appointment).where(Appointment.id == turno).values(status=estado)
    )
    await test_session.commit()
    antes = await _turnos(test_session)

    res = await client.patch(
        f"/appointments/{turno}/reschedule",
        headers=auth_headers(t.admin),
        json={
            "new_starts_at": t.dia.replace(
                hour=16, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": f"terminal-panel-{estado}-1",
        },
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "APPOINTMENT_NOT_ACTIVE"
    assert await _turnos(test_session) == antes


@pytest.mark.asyncio
async def test_el_cliente_cancela_una_vez_y_la_segunda_es_409(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _t, turno = await _con_turno(client, monkeypatch, "terminal-cancela-dos")
    url = f"/public/client/appointments/{turno}/cancel"

    primera = await client.patch(url, json={"phone": TELEFONO})
    liberados = await _eventos(test_session, EVENT_SLOT_RELEASED, turno)
    avisos = await _eventos(
        test_session, NotificationType.APPOINTMENT_CANCELLED_BY_CLIENT.value, turno
    )
    segunda = await client.patch(url, json={"phone": TELEFONO})

    assert primera.status_code == 200, primera.text
    assert (liberados, avisos) == (1, 1)
    assert segunda.status_code == 409, segunda.text
    assert segunda.json()["error_code"] == "APPOINTMENT_ALREADY_CANCELLED"
    assert await _eventos(test_session, EVENT_SLOT_RELEASED, turno) == 1
    assert (
        await _eventos(
            test_session, NotificationType.APPOINTMENT_CANCELLED_BY_CLIENT.value, turno
        )
        == 1
    )
