"""La confirmacion manual de un cobro lockea el turno y rechaza uno terminal.

Revision de perf/f4-pay (2026-09-25, #4). Sintoma:
``PaymentService.manual_confirm`` (``POST /payments/{turno}/manual-confirm``)
leia el turno sin lock y sin mirar su estado: marcaba como pagado un turno
que el personal acababa de cancelar (o uno vencido, completado o ausente).

Ahora lockea el turno primero (orden turno -> pago, regla 7), lo relee bajo
el lock y solo acepta los estados cobrables (``pending``, ``confirmed``,
``pending_payment``); cualquier otro es 409 ``APPOINTMENT_NOT_PAYABLE`` y no
crea ni toca el cobro.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.payments.model import Payment, PaymentStatus
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import _tienda
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_link_del_panel_solo_turnos_vivos import _confirmado


async def _cobros(session: AsyncSession, turno: str) -> list[Payment]:
    session.expire_all()
    return list(
        (await session.execute(select(Payment).where(Payment.appointment_id == turno)))
        .scalars()
        .all()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("estado", ["cancelled", "expired", "completed", "absent"])
async def test_no_se_confirma_a_mano_el_cobro_de_un_turno_terminal(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    estado: str,
) -> None:
    t = await _tienda(client, monkeypatch, f"manual-terminal-{estado}", sena=False)
    turno = await _confirmado(client, t, 13)
    await test_session.execute(
        update(Appointment).where(Appointment.id == turno).values(status=estado)
    )
    await test_session.commit()

    res = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(t.admin), json={}
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "APPOINTMENT_NOT_PAYABLE"
    assert await _cobros(test_session, turno) == []


@pytest.mark.asyncio
async def test_se_confirma_a_mano_el_cobro_de_un_turno_vivo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "manual-vivo", sena=False)
    turno = await _confirmado(client, t, 13)

    res = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(t.admin), json={}
    )

    assert res.status_code == 200, res.text
    (cobro,) = await _cobros(test_session, turno)
    assert cobro.status == PaymentStatus.MANUAL_CONFIRMED.value
