"""Adoptar un link retirado: todo se verifica antes y queda registrado.

Revision de e5579b6..3b977a9 (2026-09-25):

- #2: ``adopt_retired_link`` mutaba el cobro ANTES de ``_validate_payment_link``.
  Si la validacion fallaba, el webhook HTTP hace ``register_failure`` y
  commitea: la adopcion a medias quedaba guardada (el cobro con la
  preferencia del link retirado y sin aplicar el pago). Caso borde de la
  revision: flag apagado, cobro en placeholder que conserva el nonce del
  link retirado, pago con referencia vacia y la ``preference_id`` retirada.
  Ahora el pago se valida contra el link retirado ANTES de tocar el cobro.
- #3: la adopcion deja un log de info (``payment_adopted_retired_link``) con
  los ids, el importe anterior y el nuevo y los nonces; y el historial guarda
  ``original_amount``, ``discount_amount`` y ``promotion_code`` de ESE link,
  que la adopcion restaura junto con el importe (antes quedaban los del
  link vigente: el cobro decia un descuento que el pago no tuvo).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

import modules.payments.service as payments_service
from core.config import settings
from modules.payments.model import (
    EVENT_PREFERENCE_EXPIRE,
    OutboxMessage,
    Payment,
    PaymentLinkHistory,
    PaymentStatus,
    is_placeholder_preference_id,
)
from modules.payments.processing import apply_mercadopago_webhook_payload
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import (
    _cobro,
    _tienda,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_link_del_panel_solo_turnos_vivos import _confirmado
from tests.integration.test_link_regenerado_referencia_propia import (
    _MP,
    _aplicar,
    _pago_de_mp,
)


@pytest.mark.asyncio
async def test_una_adopcion_que_no_pasa_la_validacion_no_deja_nada_a_medias(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MERCADOPAGO_LINK_REF_ENABLED", True)
    t = await _tienda(client, monkeypatch, "adopcion-a-medias", sena=False)
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", _MP())
    turno = await _confirmado(client, t, 13)
    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert link.status_code == 200, link.text
    cobro = await _cobro(test_session, turno)
    retirada, nonce = str(cobro.preference_id), cobro.link_ref
    assert nonce
    # Flag apagado: retirar el link (re-tarifa sin link nuevo, o fase 2 que
    # fallo) deja el placeholder y NO rota el nonce.
    monkeypatch.setattr(settings, "MERCADOPAGO_LINK_REF_ENABLED", False)
    payments_service._retire_link(test_session, cobro)
    await test_session.commit()
    cobro = await _cobro(test_session, turno)
    assert is_placeholder_preference_id(cobro.preference_id)
    assert cobro.link_ref == nonce
    version = cobro.version

    payload = _pago_de_mp(cobro, referencia="", externo="mp-sin-referencia")
    payload["data"]["preference_id"] = retirada
    with pytest.raises(RuntimeError):
        await apply_mercadopago_webhook_payload(
            test_session, store_id=cobro.store_id, payload=payload
        )
    # Lo que hace el webhook HTTP: anota el fallo en el inbox y COMMITEA.
    await test_session.commit()

    cobro = await _cobro(test_session, turno)
    assert is_placeholder_preference_id(cobro.preference_id)
    assert (cobro.status, cobro.link_ref, cobro.version) == (
        PaymentStatus.PENDING.value,
        nonce,
        version,
    )
    filas = await test_session.scalar(
        select(func.count())
        .select_from(PaymentLinkHistory)
        .where(PaymentLinkHistory.payment_id == cobro.id)
    )
    assert filas == 1
    vencimientos = await test_session.scalar(
        select(func.count())
        .select_from(OutboxMessage)
        .where(OutboxMessage.event_type == EVENT_PREFERENCE_EXPIRE)
    )
    assert vencimientos == 0


@pytest.mark.asyncio
async def test_la_adopcion_restaura_el_descuento_del_link_y_queda_en_el_log(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MERCADOPAGO_LINK_REF_ENABLED", True)
    t = await _tienda(client, monkeypatch, "adopcion-descuento", sena=False)
    mp = _MP()
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    turno = await _confirmado(client, t, 13)
    primero = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert primero.status_code == 200, primero.text
    viejo = await _cobro(test_session, turno)
    vieja, importe_viejo, nonce_viejo = (
        str(viejo.preference_id),
        viejo.amount,
        viejo.link_ref,
    )
    # El link viejo cobraba con una promo (lo que dejaria la reserva publica).
    await test_session.execute(
        update(Payment)
        .where(Payment.id == viejo.id)
        .values(
            original_amount=importe_viejo + Decimal("500"),
            discount_amount=Decimal("500"),
            promotion_code="PROMO500",
        )
    )
    await test_session.commit()
    precio = await client.patch(
        f"/services/{t.service}", headers=auth_headers(t.admin), json={"price": 15000}
    )
    assert precio.status_code == 200, precio.text
    segundo = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.admin)
    )
    assert segundo.status_code == 200, segundo.text
    cobro = await _cobro(test_session, turno)
    importe_nuevo, nonce_nuevo = cobro.amount, cobro.link_ref
    assert importe_nuevo != importe_viejo

    payload = _pago_de_mp(cobro, referencia=mp.referencias[vieja], externo="mp-viejo")
    payload["data"]["transaction_amount"] = float(importe_viejo)
    with capture_logs() as logs:
        aplicado = await _aplicar(test_session, cobro, payload)

    assert aplicado is True
    cobro = await _cobro(test_session, turno)
    assert (
        cobro.status,
        cobro.amount,
        cobro.original_amount,
        cobro.discount_amount,
        cobro.promotion_code,
    ) == (
        PaymentStatus.APPROVED.value,
        importe_viejo,
        importe_viejo + Decimal("500"),
        Decimal("500"),
        "PROMO500",
    )
    adopciones = [e for e in logs if e["event"] == "payment_adopted_retired_link"]
    assert len(adopciones) == 1, logs
    adopcion = adopciones[0]
    assert adopcion["log_level"] == "info"
    assert (adopcion["store_id"], adopcion["payment_id"]) == (
        cobro.store_id,
        cobro.id,
    )
    assert adopcion["appointment_id"] == turno
    assert (adopcion["previous_amount"], adopcion["amount"]) == (
        str(importe_nuevo),
        str(importe_viejo),
    )
    assert (adopcion["previous_link_ref"], adopcion["link_ref"]) == (
        nonce_nuevo,
        nonce_viejo,
    )
