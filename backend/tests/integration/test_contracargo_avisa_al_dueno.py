"""Un contracargo de Mercado Pago se registra y se avisa al dueno.

2026-09-20, AUD2-B2-04: ``resolve_payment_status`` mapeaba 8 valores. Mercado
Pago tambien manda ``charged_back`` (contracargo: la plata vuelve al cliente),
``in_mediation`` (disputa abierta) y ``authorized`` (fondos retenidos, sin
capturar). Ninguno estaba en el mapa, asi que la funcion devolvia None,
``apply_mercadopago_webhook_payload`` devolvia False, el inbox anotaba "No se
pudo resolver el pago del webhook", reintentaba 10 veces y lo abandonaba.

Sintoma: el ``Payment`` quedaba ``approved``, el turno ``confirmed``, la
conciliacion sumaba esa plata en ``total_approved_amount`` y el dueno no
recibia ningun aviso: solo veia un numero en ``failed_webhooks`` (reglas 7 y
11).

El grafo ya admite ``approved -> refunded``, asi que no hace falta un estado
ni una arista nueva (regla 2 intacta, sin migracion). El turno confirmado se
mantiene confirmado -- el criterio de ``sync_appointment_with_payment`` para
``refunded``, que es decision escrita del dueno --, pero ahora con un aviso
propio en el panel: un contracargo NO puede dejar el turno confirmado en
silencio.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from modules.notifications.model import Notification
from modules.payments.jobs import process_outbox_batch, process_webhook_inbox_batch
from modules.payments.model import OutboxMessage, Payment, PaymentStatus, WebhookInbox
from modules.payments.processing import resolve_payment_status
from modules.appointments.model import Appointment, AppointmentStatus
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


def _mercadopago_con_estado(
    monkeypatch: pytest.MonkeyPatch, remoto: dict[str, Any]
) -> None:
    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return {
                "id": "pref-contracargo",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=cb",
            }
        return remoto

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


async def _entregar_webhook(
    client: AsyncClient, store: str, *, evento: str, pago: str
) -> None:
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


def _remoto(turno: str, cobro: Payment, estado: str) -> dict[str, Any]:
    return {
        "id": "mp-pago-contracargo",
        "status": estado,
        "external_reference": turno,
        "preference_id": cobro.preference_id,
        "transaction_amount": float(cobro.amount),
        "currency_id": cobro.currency,
        "metadata": {"appointment_id": turno},
    }


@pytest.mark.asyncio
async def test_un_contracargo_deja_el_cobro_devuelto_y_avisa_al_dueno(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago_con_estado(monkeypatch, {})
    store, token = await register_and_login(
        client, slug="contracargo", email="contracargo@t.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix="contracargo", hour=10
    )
    cobro = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == turno)
        )
    ).scalar_one()

    _mercadopago_con_estado(monkeypatch, _remoto(turno, cobro, "approved"))
    await _entregar_webhook(client, store, evento="evt-ok", pago="mp-pago-contracargo")
    await test_session.refresh(cobro)
    assert cobro.status == PaymentStatus.APPROVED.value

    _mercadopago_con_estado(monkeypatch, _remoto(turno, cobro, "charged_back"))
    await _entregar_webhook(client, store, evento="evt-cb", pago="mp-pago-contracargo")

    await test_session.refresh(cobro)
    assert cobro.status == PaymentStatus.REFUNDED.value
    eventos = (await test_session.execute(select(WebhookInbox))).scalars().all()
    assert len(eventos) == 2, eventos
    assert all(e.processed_at is not None for e in eventos), [e.error for e in eventos]

    await process_outbox_batch(test_session)
    avisos = list(
        (
            await test_session.execute(
                select(Notification).where(Notification.type == "payment.charged_back")
            )
        )
        .scalars()
        .all()
    )
    assert len(avisos) == 1, avisos
    assert avisos[0].appointment_id == turno
    # El turno sigue confirmado (criterio de sync_appointment_with_payment para
    # refunded), pero ya no en silencio: el dueno tiene el aviso.
    appointment = (
        await test_session.execute(select(Appointment).where(Appointment.id == turno))
    ).scalar_one()
    assert appointment.status == AppointmentStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_una_disputa_abierta_no_agota_los_reintentos_del_inbox(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``in_mediation`` es "todavia no hay plata", no "no se pudo resolver"."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago_con_estado(monkeypatch, {})
    store, token = await register_and_login(
        client, slug="disputa", email="disputa@t.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix="disputa", hour=11
    )
    cobro = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == turno)
        )
    ).scalar_one()

    _mercadopago_con_estado(monkeypatch, _remoto(turno, cobro, "in_mediation"))
    await _entregar_webhook(
        client, store, evento="evt-disputa", pago="mp-pago-contracargo"
    )

    evento = (await test_session.execute(select(WebhookInbox))).scalar_one()
    assert evento.processed_at is not None, evento.error
    assert evento.attempts == 0, evento.error
    await test_session.refresh(cobro)
    assert cobro.status == PaymentStatus.PENDING.value


@pytest.mark.asyncio
async def test_una_disputa_sobre_un_cobro_acreditado_avisa_al_dueno(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``in_mediation`` sobre un ``approved`` no cambia el estado, pero avisa.

    V-diff de AUD2-B2-04 (2026-09-20): el mapeo a ``pending`` alcanzaba para
    un cobro que todavia no se acredito, pero sobre uno ``approved`` la
    transicion ``approved -> pending`` es ilegal, se ignoraba en silencio y el
    inbox se sellaba: Mercado Pago retenia la plata y el dueno no se enteraba.
    Decision: el cobro sigue ``approved`` (sin estado ni arista nueva, regla 2)
    y se publica ``payment.in_mediation`` al outbox, con el mismo consumidor
    que el contracargo.
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago_con_estado(monkeypatch, {})
    store, token = await register_and_login(
        client, slug="disputa-acreditada", email="disputa-acreditada@t.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix="disputa-acreditada", hour=13
    )
    cobro = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == turno)
        )
    ).scalar_one()

    _mercadopago_con_estado(monkeypatch, _remoto(turno, cobro, "approved"))
    await _entregar_webhook(client, store, evento="evt-ok3", pago="mp-pago-contracargo")
    _mercadopago_con_estado(monkeypatch, _remoto(turno, cobro, "in_mediation"))
    await _entregar_webhook(client, store, evento="evt-med", pago="mp-pago-contracargo")

    await test_session.refresh(cobro)
    assert cobro.status == PaymentStatus.APPROVED.value
    eventos = (await test_session.execute(select(WebhookInbox))).scalars().all()
    assert len(eventos) == 2, eventos
    assert all(e.processed_at is not None for e in eventos), [e.error for e in eventos]
    disputas = (
        (
            await test_session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == "payment.in_mediation"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(disputas) == 1, disputas
    assert disputas[0].payload and disputas[0].payload["appointment_id"] == turno

    await process_outbox_batch(test_session)
    avisos = list(
        (
            await test_session.execute(
                select(Notification).where(Notification.type == "payment.in_mediation")
            )
        )
        .scalars()
        .all()
    )
    assert len(avisos) == 1, avisos
    assert avisos[0].appointment_id == turno
    assert "retenida" in (avisos[0].body or "")


def test_los_estados_que_mercado_pago_manda_y_no_estaban_mapeados() -> None:
    def estado(valor: str) -> str | None:
        return resolve_payment_status({"data": {"id": "x", "status": valor}})

    assert estado("charged_back") == PaymentStatus.REFUNDED.value
    assert estado("in_mediation") == PaymentStatus.PENDING.value
    assert estado("authorized") == PaymentStatus.PENDING.value
    # Lo que ya funcionaba sigue igual.
    assert estado("approved") == PaymentStatus.APPROVED.value
    assert estado("cancelled") == PaymentStatus.REJECTED.value
    assert estado("cualquier_cosa") is None


@pytest.mark.asyncio
async def test_el_lote_del_inbox_tambien_aplica_el_contracargo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El mismo evento por el lote (webhook que llego sin poder aplicarse)."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago_con_estado(monkeypatch, {})
    store, token = await register_and_login(
        client, slug="cb-lote", email="cb-lote@t.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix="cb-lote", hour=12
    )
    cobro = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == turno)
        )
    ).scalar_one()
    store_id = cobro.store_id

    _mercadopago_con_estado(monkeypatch, _remoto(turno, cobro, "approved"))
    await _entregar_webhook(client, store, evento="evt-ok2", pago="mp-pago-contracargo")

    _mercadopago_con_estado(monkeypatch, _remoto(turno, cobro, "charged_back"))
    test_session.add(
        WebhookInbox(
            store_id=store_id,
            provider="mercadopago",
            event_id="evt-cb-lote",
            event_type="payment",
            payload={"type": "payment", "data": {"id": "mp-pago-contracargo"}},
        )
    )
    await test_session.commit()

    stats = await process_webhook_inbox_batch(test_session)

    assert stats == {"processed": 1, "failed": 0, "inspected": 1}, stats
    await test_session.refresh(cobro)
    assert cobro.status == PaymentStatus.REFUNDED.value


def test_el_grafo_de_pagos_no_cambio() -> None:
    """Regla 2: el contracargo entra por una arista que ya existia."""
    from modules.payments.model import ALLOWED_PAYMENT_TRANSITIONS

    assert PaymentStatus.REFUNDED.value in ALLOWED_PAYMENT_TRANSITIONS["approved"]
    assert ALLOWED_PAYMENT_TRANSITIONS["refunded"] == set()
