"""Un webhook con importe inconsistente no devuelve 500 ni pierde la fila del inbox.

2026-09-16, hallazgo B2-04: ``_validate_payment_link`` levanta
``RuntimeError`` cuando el importe, la moneda, la referencia, la preferencia o
el collector no coinciden. En el camino HTTP esa excepcion no se capturaba:
subia al handler generico (500), la transaccion no commiteaba y el
``WebhookInbox`` recien agregado se perdia. Sintoma: la tienda regenera el link
con otro importe (o MP acredita un monto distinto) y cada reentrega de MP
devuelve 500 hasta que MP agota sus reintentos; el pago queda ``pending`` sin
rastro en ``failed_webhooks`` y el turno vence con la plata ya cobrada.

Regla 7: el inbox es el mecanismo de reintento; ``processed_at`` solo si se
aplico de verdad. Regla 20: errores neutros hacia afuera.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import Payment, PaymentStatus, WebhookInbox
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
    webhook_signature_headers,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _approved_remote_payment,
    _book_with_mercadopago,
    _configure_gateway,
    _enable_payments,
    _stub_mercadopago,
)


async def _entregar(client: AsyncClient, store: str) -> Any:
    return await client.post(
        f"/payments/webhooks/mercadopago?store_id={store}",
        json={"id": "evt-b204", "type": "payment", "data": {"id": "mp-b204"}},
        headers=webhook_signature_headers(
            secret="secret-demo",
            data_id="mp-b204",
            request_id="req-b204",
            ts="1710000000",
        ),
    )


@pytest.mark.asyncio
async def test_importe_inconsistente_responde_200_y_deja_el_evento_en_el_inbox(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    store, token = await register_and_login(
        client, slug="b204-importe", email="b204@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    appointment_id = await _book_with_mercadopago(
        client, token, store, slug_suffix="b204", hour=10
    )
    payment = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == appointment_id)
        )
    ).scalar_one()

    # Mercado Pago dice "aprobado", pero por la MITAD de la sena esperada.
    remoto = {
        **_approved_remote_payment(payment),
        "id": "mp-b204",
        "transaction_amount": float(payment.amount) / 2,
    }
    _stub_mercadopago(monkeypatch, remote_payment=remoto)

    respuesta = await _entregar(client, store)

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    datos = cuerpo.get("data", cuerpo)
    assert datos == {"received": True, "applied": False}

    inbox = (await test_session.execute(select(WebhookInbox))).scalar_one()
    assert inbox.processed_at is None, "no se aplico: tiene que quedar reintentable"
    assert inbox.attempts == 1
    assert "importe" in (inbox.error or "").lower(), inbox.error

    await test_session.refresh(payment)
    assert payment.status == PaymentStatus.PENDING.value
    assert payment.external_payment_id is None, "no se toco el pago"
    turno = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
    ).scalar_one()
    assert turno.status == AppointmentStatus.PENDING_PAYMENT.value

    # Queda visible para el dueno en la conciliacion.
    resumen = await client.get(
        "/payments/reconciliation/summary", headers=auth_headers(token)
    )
    assert resumen.status_code == 200, resumen.text
    assert resumen.json()["failed_webhooks"] == 1

    # La reentrega de MP (mismo event_id) suma un intento sobre la MISMA fila.
    reentrega = await _entregar(client, store)
    assert reentrega.status_code == 200, reentrega.text
    await test_session.refresh(inbox)
    assert inbox.attempts == 2
    assert inbox.processed_at is None
    total = await test_session.scalar(select(func.count()).select_from(WebhookInbox))
    assert total == 1
