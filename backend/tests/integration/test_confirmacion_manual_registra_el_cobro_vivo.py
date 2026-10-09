"""Confirmar a mano sin importe registra el importe del cobro VIVO.

2026-10-08, revision de la PR #131 (C1). Sintoma: un turno completado con
precio congelado 3200; "Crear link" desde Cobros deja un cobro ``pending``
SIN ``deposit_rule`` por otro importe (la sena del servicio). La tarjeta
muestra ese importe, el dialogo "Confirmar pago" lo propone y, si el usuario
lo deja como esta, el front no manda ``amount``. El backend solo conservaba el
importe de un cobro con snapshot ``deposit_rule``: este lo re-tarifaba al
precio del turno y registraba ``manual_confirmed`` por 3200 cuando la pantalla
decia otra cosa.

Ahora, sin ``amount``, un cobro vivo (``LIVE_CHARGE_PAYMENT_STATUSES``:
``pending`` o ``rejected``) se registra por SU importe, venga de donde venga,
y conserva promo y descuento. Sin cobro vivo el importe sigue siendo el
precio congelado del turno (el front manda siempre el que mostro).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.payments.model import PaymentStatus
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import (
    _cobro,
    _tienda,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_link_del_panel_solo_turnos_vivos import _confirmado

PRECIO_DEL_TURNO = Decimal("3200.00")


async def _precio_del_turno(session: AsyncSession, turno: str) -> None:
    """El precio congelado del turno distinto del importe del link."""
    await session.execute(
        update(Appointment)
        .where(Appointment.id == turno)
        .values(price_amount=PRECIO_DEL_TURNO)
    )
    await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("estado", [PaymentStatus.PENDING, PaymentStatus.REJECTED])
async def test_sin_importe_registra_el_importe_del_link_del_panel(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    estado: PaymentStatus,
) -> None:
    t = await _tienda(client, monkeypatch, f"c1-vivo-{estado.value}", sena=False)
    turno = await _confirmado(client, t, 14)
    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert link.status_code == 200, link.text
    cobro = await _cobro(test_session, turno)
    assert cobro.deposit_rule is None
    if estado is PaymentStatus.REJECTED:
        assert cobro.apply_status(PaymentStatus.REJECTED.value)
        await test_session.commit()
    importe_del_link = cobro.amount
    await _precio_del_turno(test_session, turno)
    assert importe_del_link != PRECIO_DEL_TURNO

    res = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(t.admin), json={}
    )

    assert res.status_code == 200, res.text
    assert Decimal(res.json()["amount"]) == importe_del_link
    cobro = await _cobro(test_session, turno)
    assert cobro.status == PaymentStatus.MANUAL_CONFIRMED.value
    assert cobro.amount == importe_del_link


@pytest.mark.asyncio
async def test_sin_cobro_y_sin_importe_registra_el_precio_del_turno(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "c1-sin-cobro", sena=False)
    turno = await _confirmado(client, t, 15)
    await _precio_del_turno(test_session, turno)

    res = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(t.admin), json={}
    )

    assert res.status_code == 200, res.text
    assert Decimal(res.json()["amount"]) == PRECIO_DEL_TURNO
    cobro = await _cobro(test_session, turno)
    assert cobro.status == PaymentStatus.MANUAL_CONFIRMED.value
    assert cobro.amount == PRECIO_DEL_TURNO
