"""Confirmar un cobro a mano no re-tarifa la seña ni borra el link de Mercado Pago.

2026-09-19, AUD2-B2-01: ``PaymentService.manual_confirm`` entraba a
``ensure_payment_preference`` sin ``keep_existing_amount``, asi que el cobro
pasaba de la seña al precio congelado del turno, ``promotion_code`` se
borraba, el snapshot ``deposit_rule`` quedaba mintiendo y, como el importe
cambiaba sin pedir link nuevo, ``_needs_provider_link`` pisaba el
``preference_id`` REAL con el placeholder. La preferencia seguia viva en
Mercado Pago (nadie la vencia) y Shifty ya no sabia cual era: si el cliente
pagaba ese link, el webhook lo rechazaba por importe y por preferencia, el
inbox lo reintentaba 10 veces y lo abandonaba. La tienda cobraba dos veces
sin registro.

El ``amount`` explicito del pedido sigue siendo el unico que re-tarifa.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.payments.model import Payment, PaymentStatus
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _book_with_mercadopago,
    _configure_gateway,
    _enable_payments,
    _stub_preference,
)

PREFERENCIA_REAL = "pref-hardening"  # la que devuelve _stub_preference


async def _turno_con_sena(
    client: AsyncClient, session: AsyncSession, slug: str, hour: int
) -> tuple[str, str, Payment]:
    _store_public_id, token = await register_and_login(
        client, slug=slug, email=f"{slug}@t.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, _store_public_id, slug_suffix=slug, hour=hour
    )
    pago = (
        await session.execute(select(Payment).where(Payment.appointment_id == turno))
    ).scalar_one()
    return token, turno, pago


@pytest.mark.asyncio
async def test_confirmar_a_mano_conserva_la_sena_el_snapshot_y_el_link_real(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_preference(monkeypatch)
    token, turno, pago = await _turno_con_sena(client, test_session, "aud2-01-sena", 10)
    sena = pago.amount
    assert pago.deposit_rule is not None
    assert pago.preference_id == PREFERENCIA_REAL

    confirmado = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(token), json={}
    )
    assert confirmado.status_code == 200, confirmado.text

    test_session.expire_all()
    pago = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == turno)
        )
    ).scalar_one()
    assert pago.status == PaymentStatus.MANUAL_CONFIRMED.value
    # El importe sigue siendo la seña y el snapshot no miente.
    assert pago.amount == sena
    assert Decimal(str(cast(dict[str, str], pago.deposit_rule)["amount"])) == sena
    # Y el link de Mercado Pago sigue siendo el real, no el placeholder.
    assert pago.preference_id == PREFERENCIA_REAL
    assert pago.payment_link and "payments.shifty.local" not in pago.payment_link


@pytest.mark.asyncio
async def test_un_importe_explicito_sigue_re_tarifando(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El dueno puede registrar otro importe: es el unico camino que re-tarifa."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_preference(monkeypatch)
    token, turno, _pago = await _turno_con_sena(
        client, test_session, "aud2-01-monto", 11
    )

    confirmado = await client.post(
        f"/payments/{turno}/manual-confirm",
        headers=auth_headers(token),
        json={"amount": "5000.00", "notes": "cobrado en efectivo"},
    )
    assert confirmado.status_code == 200, confirmado.text
    assert confirmado.json()["amount"] == "5000.00"
