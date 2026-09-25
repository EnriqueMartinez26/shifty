"""Un bloqueo que cancela un turno con cobro vivo vence el cobro.

RECHAZO de la revision de perf/f4-pay (2026-09-25, #1). Sintoma:
``AppointmentBlockService._classify`` solo salteaba ``pending_payment`` y los
pagos acreditados, y ``_cancel_for_block`` cancelaba un turno CONFIRMADO o
PENDIENTE con un link del panel en ``pending``/``rejected`` sin vencerlo: el
link de Mercado Pago quedaba vivo sobre un turno cancelado. Pasaba al crear un
bloqueo, al cerrar la tienda (``staff_id=None``) y al editar un bloqueo.

Regla de Mateo adoptada por el dueno (D2: lo que hace el personal vence el cobro): la cancelacion
por bloqueo vence el cobro vivo con el mismo camino compartido
(``payments.service.expire_live_charge``), en la misma transaccion, con el
turno lockeado antes que el pago.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.payments.model import PaymentStatus
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import (
    PREFERENCIA,
    _cobro,
    _confirmado_con_link,
    _tienda,
    _Tienda,
    _vencimientos,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)


def _a_las(t: _Tienda, hora: int) -> datetime:
    return t.dia.replace(hour=hora, minute=0, second=0, microsecond=0)


async def _bloquear(client: AsyncClient, t: _Tienda, modo: str) -> Response:
    rango = {
        "starts_at": _a_las(t, 12).isoformat(),
        "ends_at": _a_las(t, 15).isoformat(),
        "cancel_affected": True,
    }
    if modo == "profesional":
        return await client.post(
            "/appointment-blocks/",
            headers=auth_headers(t.admin),
            json={**rango, "staff_id": t.staff, "reason": "Tramite"},
        )
    if modo == "tienda":
        return await client.post(
            "/appointment-blocks/store-wide",
            headers=auth_headers(t.admin),
            json={**rango, "reason": "Cerrado"},
        )
    # Edicion: un bloqueo que no toca el turno y despues se mueve encima.
    alta = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(t.admin),
        json={
            "staff_id": t.staff,
            "starts_at": _a_las(t, 16).isoformat(),
            "ends_at": _a_las(t, 17).isoformat(),
            "reason": "Tramite",
        },
    )
    assert alta.status_code == 201, alta.text
    return await client.patch(
        f"/appointment-blocks/{alta.json()['public_id']}",
        headers=auth_headers(t.admin),
        json=rango,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("modo", ["profesional", "tienda", "edicion"])
@pytest.mark.parametrize("cobro", [PaymentStatus.PENDING, PaymentStatus.REJECTED])
async def test_el_bloqueo_que_cancela_un_turno_con_link_vivo_lo_vence(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    modo: str,
    cobro: PaymentStatus,
) -> None:
    t = await _tienda(client, monkeypatch, f"bloq-{modo}-{cobro.value}", sena=False)
    turno = await _confirmado_con_link(client, t, 13)
    if cobro is PaymentStatus.REJECTED:
        pago = await _cobro(test_session, turno)
        assert pago.apply_status(PaymentStatus.REJECTED.value)
        await test_session.commit()
    llamadas_antes = len(t.llamadas_mp)

    res = await _bloquear(client, t, modo)

    assert res.status_code in {200, 201}, res.text
    test_session.expire_all()
    quedo = (
        await test_session.execute(select(Appointment).where(Appointment.id == turno))
    ).scalar_one()
    assert quedo.status == "cancelled"
    pago = await _cobro(test_session, turno)
    estado = pago.status
    assert estado == PaymentStatus.EXPIRED.value
    eventos = await _vencimientos(test_session, turno)
    assert [e.payload["preference_id"] for e in eventos] == [PREFERENCIA]
    # Regla 5: ninguna llamada a MP en el request; la hace el outbox.
    assert t.llamadas_mp[llamadas_antes:] == []
