"""El webhook no pisa ``external_payment_id`` si descarta la transicion.

2026-09-20, AUD2-B2-05: ``apply_mercadopago_webhook_payload`` escribia
``payment.external_payment_id`` ANTES de saber si la transicion se aplicaba.
Si el cliente reintentaba en Mercado Pago (pago A aprobado, pago B rechazado
sobre la misma preferencia), el webhook de B se resolvia por
``preference_id``, pasaba la validacion (mismo importe, misma preferencia) y
escribia ``external_payment_id = B``; ``apply_status("rejected")`` desde
``approved`` devolvia False y se ignoraba, pero el id ya habia quedado
cambiado. ``raw_payload`` seguia siendo el de A, asi que la fila se
contradecia y quien quisiera devolver la plata miraba el id del pago
rechazado (regla 2: el ``external_payment_id`` es parte del estado del cobro
y se estaba escribiendo por fuera de la transicion que valida la entidad).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from modules.payments.model import Payment, PaymentStatus
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
    webhook_signature_headers,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _book_with_mercadopago,
    _configure_gateway,
    _enable_payments,
)


def _mercadopago(monkeypatch: pytest.MonkeyPatch, remoto: dict[str, Any]) -> None:
    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return {
                "id": "pref-reintento",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=r",
            }
        return remoto

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


def _pago_remoto(
    turno: str, cobro: Payment, *, pago: str, estado: str
) -> dict[str, Any]:
    return {
        "id": pago,
        "status": estado,
        "external_reference": cobro.current_external_reference,
        "preference_id": cobro.preference_id,
        "transaction_amount": float(cobro.amount),
        "currency_id": cobro.currency,
    }


async def _entregar(client: AsyncClient, store: str, *, evento: str, pago: str) -> None:
    respuesta = await client.post(
        f"/payments/webhooks/mercadopago?store_id={store}",
        json={"id": evento, "type": "payment", "data": {"id": pago}},
        headers=webhook_signature_headers(
            secret="secret-demo",
            data_id=pago,
            request_id=f"req-{evento}",
            ts="1710000000",
        ),
    )
    assert respuesta.status_code == 200, respuesta.text


@pytest.mark.asyncio
async def test_un_rechazo_posterior_no_cambia_el_id_del_pago_acreditado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago(monkeypatch, {})
    store, token = await register_and_login(
        client, slug="reintento-mp", email="reintento-mp@t.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix="reintento-mp", hour=10
    )
    cobro = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == turno)
        )
    ).scalar_one()

    # Pago A: aprobado.
    _mercadopago(
        monkeypatch, _pago_remoto(turno, cobro, pago="pago-A", estado="approved")
    )
    await _entregar(client, store, evento="evt-a", pago="pago-A")
    await test_session.refresh(cobro)
    assert cobro.status == PaymentStatus.APPROVED.value
    assert cobro.external_payment_id == "pago-A"

    # Pago B: el cliente reintento y le salio rechazado, misma preferencia.
    _mercadopago(
        monkeypatch, _pago_remoto(turno, cobro, pago="pago-B", estado="rejected")
    )
    await _entregar(client, store, evento="evt-b", pago="pago-B")

    await test_session.refresh(cobro)
    assert cobro.status == PaymentStatus.APPROVED.value
    assert cobro.external_payment_id == "pago-A", (
        "el webhook descartado del pago rechazado piso el id del pago que si "
        "se acredito: para reembolsar se mira el id equivocado"
    )
    # raw_payload y external_payment_id tienen que hablar del MISMO pago.
    datos = (cobro.raw_payload or {}).get("data")
    assert isinstance(datos, dict) and datos.get("id") == "pago-A", cobro.raw_payload


@pytest.mark.asyncio
async def test_el_webhook_que_se_aplica_sigue_dejando_el_id_del_pago(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda del camino feliz: mover la escritura despues de la transicion no
    puede perder la trazabilidad cuando la transicion SI se aplica."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago(monkeypatch, {})
    store, token = await register_and_login(
        client, slug="reintento-vacio", email="reintento-vacio@t.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix="reintento-vacio", hour=11
    )
    cobro = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == turno)
        )
    ).scalar_one()
    assert cobro.external_payment_id is None

    _mercadopago(
        monkeypatch, _pago_remoto(turno, cobro, pago="pago-C", estado="pending")
    )
    await _entregar(client, store, evento="evt-c", pago="pago-C")

    await test_session.refresh(cobro)
    assert cobro.status == PaymentStatus.PENDING.value
    assert cobro.external_payment_id == "pago-C"
