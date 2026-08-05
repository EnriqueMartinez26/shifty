"""Cobertura de las reglas que protegen el dinero y el respaldo legal.

Complementa a ``test_feature_flags_finance_and_public_privacy`` enfocandose en
los flujos nuevos: reintento de webhooks, seña obligatoria, retencion corta del
slot, notificaciones al dueño y consentimiento del cliente.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import Notification, NotificationType
from modules.payments.jobs import (
    expire_unpaid_appointments,
    process_outbox_batch,
    process_webhook_inbox_batch,
    reconcile_pending_payments,
)
from modules.payments.model import (
    WEBHOOK_INBOX_MAX_ATTEMPTS,
    Payment,
    PaymentStatus,
    WebhookInbox,
)

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
    webhook_signature_headers,
)


async def _enable_payments(client: AsyncClient, token: str) -> None:
    res = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert res.status_code == 200, res.text


async def _configure_gateway(client: AsyncClient, token: str) -> None:
    res = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={
            "access_token": "TEST-ACCESS-TOKEN-1234567890",
            "public_key": "TEST-PUBLIC-KEY",
            "webhook_secret": "secret-demo",
        },
    )
    assert res.status_code == 200, res.text


def _stub_preference(monkeypatch: pytest.MonkeyPatch) -> None:
    import modules.payments.service as payments_service

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": "pref-hardening",
            "init_point": "https://www.mercadopago.com/checkout/v1/redirect?pref=hardening",
        }

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


def _stub_mercadopago(
    monkeypatch: pytest.MonkeyPatch, *, remote_payment: dict[str, Any] | None
) -> None:
    """Simula la API de Mercado Pago: preferencia, consulta y busqueda de pagos."""
    import modules.payments.service as payments_service

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return {
                "id": "pref-hardening",
                "init_point": (
                    "https://www.mercadopago.com/checkout/v1/redirect?pref=hardening"
                ),
            }
        if path.startswith("/v1/payments/search"):
            return {"results": [remote_payment] if remote_payment else []}
        if path.startswith("/v1/payments/"):
            return remote_payment or {}
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


async def _book_with_mercadopago(
    client: AsyncClient,
    token: str,
    store_public_id: str,
    *,
    slug_suffix: str,
    hour: int,
) -> str:
    service_public_id = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)
    slot = starts_at.replace(hour=hour, minute=0, second=0, microsecond=0)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": slot.isoformat(),
            "client_name": "Cliente MP",
            "client_phone": "+5491155588888",
            "payment_method": "mercadopago",
            "accepts_terms": True,
            "idempotency_key": f"mp-booking-{slug_suffix}",
        },
    )
    assert booking.status_code == 201, booking.text
    return cast(str, booking.json()["public_id"])


def _approved_remote_payment(payment: Payment) -> dict[str, Any]:
    return {
        "id": "mp-remote-1",
        "status": "approved",
        "external_reference": payment.appointment_id,
        "preference_id": payment.preference_id,
        "transaction_amount": float(payment.amount),
        "currency_id": payment.currency,
    }


@pytest.mark.asyncio
async def test_reconciliation_recovers_a_payment_whose_webhook_never_arrived(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si la notificacion nunca llego, el cobro se recupera preguntandole a Mercado Pago."""
    _stub_mercadopago(monkeypatch, remote_payment=None)
    store_public_id, token = await register_and_login(
        client, slug="tienda-concilia-job", email="concilia-job@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    appointment_id = await _book_with_mercadopago(
        client, token, store_public_id, slug_suffix="reconcile", hour=9
    )

    payment = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == appointment_id)
        )
    ).scalar_one()
    assert payment.status == PaymentStatus.PENDING.value

    _stub_mercadopago(monkeypatch, remote_payment=_approved_remote_payment(payment))
    stats = await reconcile_pending_payments(test_session)
    assert stats["reconciled"] == 1

    await test_session.refresh(payment)
    assert payment.status == PaymentStatus.APPROVED.value

    appointment = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
    ).scalar_one()
    assert appointment.status == AppointmentStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_expiry_rescues_an_appointment_that_was_actually_paid(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un turno pagado no puede vencerse solo porque el webhook se perdio."""
    _stub_mercadopago(monkeypatch, remote_payment=None)
    store_public_id, token = await register_and_login(
        client, slug="tienda-rescate", email="rescate@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    appointment_id = await _book_with_mercadopago(
        client, token, store_public_id, slug_suffix="rescue", hour=10
    )

    appointment = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
    ).scalar_one()
    appointment.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await test_session.commit()

    payment = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == appointment_id)
        )
    ).scalar_one()
    _stub_mercadopago(monkeypatch, remote_payment=_approved_remote_payment(payment))

    stats = await expire_unpaid_appointments(test_session)
    assert stats["rescued"] == 1
    assert stats["expired"] == 0

    await test_session.refresh(appointment)
    assert appointment.status == AppointmentStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_expiry_releases_the_slot_when_nothing_was_paid(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin cobro acreditado, el turno vence y el horario vuelve a estar disponible."""
    _stub_mercadopago(monkeypatch, remote_payment=None)
    store_public_id, token = await register_and_login(
        client, slug="tienda-vence", email="vence@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    appointment_id = await _book_with_mercadopago(
        client, token, store_public_id, slug_suffix="expire", hour=11
    )

    appointment = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
    ).scalar_one()
    appointment.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await test_session.commit()

    stats = await expire_unpaid_appointments(test_session)
    assert stats["expired"] == 1
    assert stats["rescued"] == 0

    await test_session.refresh(appointment)
    assert appointment.status == AppointmentStatus.EXPIRED.value


@pytest.mark.asyncio
async def test_webhook_inbox_gives_up_after_exhausting_retries(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Un evento irrecuperable deja de reintentarse y queda contabilizado como fallido."""
    store_public_id, token = await register_and_login(
        client, slug="tienda-agota", email="agota@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)

    await client.post(
        f"/payments/webhooks/mercadopago?store_id={store_public_id}",
        json={"id": "evt-agota", "type": "payment", "data": {"id": "pay-agota"}},
        headers=webhook_signature_headers(
            secret="secret-demo",
            data_id="pay-agota",
            request_id="req-agota",
            ts="1710000000",
        ),
    )

    inbox = (await test_session.execute(select(WebhookInbox))).scalar_one()
    assert inbox.attempts == 1

    for _ in range(WEBHOOK_INBOX_MAX_ATTEMPTS):
        await process_webhook_inbox_batch(test_session)

    await test_session.refresh(inbox)
    assert inbox.attempts >= WEBHOOK_INBOX_MAX_ATTEMPTS
    assert inbox.processed_at is not None, "debe dejar de reintentarse"
    assert inbox.error


@pytest.mark.asyncio
async def test_unresolvable_webhook_stays_pending_for_retry(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Un webhook que no pudimos aplicar no debe darse por procesado.

    Marcarlo perderia el cobro de forma permanente: el turno venceria aunque el
    cliente haya pagado.
    """
    store_public_id, token = await register_and_login(
        client, slug="tienda-retry", email="retry@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)

    payload = {"id": "evt-retry", "type": "payment", "data": {"id": "pay-retry"}}
    response = await client.post(
        f"/payments/webhooks/mercadopago?store_id={store_public_id}",
        json=payload,
        headers=webhook_signature_headers(
            secret="secret-demo",
            data_id="pay-retry",
            request_id="req-retry",
            ts="1710000000",
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    payload_body = body.get("data", body)
    assert payload_body["applied"] is False

    result = await test_session.execute(select(WebhookInbox))
    inbox = result.scalar_one()
    assert inbox.processed_at is None, "el evento debe quedar disponible para reintento"
    assert inbox.attempts == 1
    assert inbox.error


@pytest.mark.asyncio
async def test_required_deposit_blocks_manual_when_store_disallows_coordination(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin coordinacion manual habilitada, la seña obligatoria no se puede saltear."""
    _stub_preference(monkeypatch)
    store_public_id, token = await register_and_login(
        client, slug="tienda-obligatoria", email="obligatoria@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)

    settings_update = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"allow_manual_coordination": False},
    )
    assert settings_update.status_code == 200, settings_update.text
    assert settings_update.json()["allow_manual_coordination"] is False

    service_public_id = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=3)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)
    slot = starts_at.replace(hour=10, minute=0, second=0, microsecond=0)

    blocked = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": slot.isoformat(),
            "client_name": "Cliente Evasor",
            "client_phone": "+5491155522222",
            "payment_method": "manual",
            "idempotency_key": "blocked-manual-booking-001",
        },
    )
    assert blocked.status_code == 422, blocked.text
    assert "Mercado Pago" in blocked.text


@pytest.mark.asyncio
async def test_required_deposit_allows_manual_when_store_opts_in(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si la tienda acepta coordinar por fuera, la reserva manual sigue siendo valida."""
    _stub_preference(monkeypatch)
    store_public_id, token = await register_and_login(
        client, slug="tienda-flexible", email="flexible@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)

    service_public_id = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=3)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)
    slot = starts_at.replace(hour=11, minute=0, second=0, microsecond=0)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": slot.isoformat(),
            "client_name": "Cliente Coordinado",
            "client_phone": "+5491155533333",
            "payment_method": "manual",
            "accepts_terms": True,
            "idempotency_key": "allowed-manual-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    assert booking.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_mercadopago_hold_expires_long_before_the_appointment(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El slot no puede quedar bloqueado hasta la hora del turno sin haberse pagado."""
    _stub_preference(monkeypatch)
    store_public_id, token = await register_and_login(
        client, slug="tienda-hold", email="hold@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)

    service_public_id = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=50,
    )
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)
    slot = starts_at.replace(hour=12, minute=0, second=0, microsecond=0)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": slot.isoformat(),
            "client_name": "Cliente Retencion",
            "client_phone": "+5491155544444",
            "payment_method": "mercadopago",
            "accepts_terms": True,
            "idempotency_key": "hold-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    appointment_id = cast(str, booking.json()["public_id"])

    result = await test_session.execute(
        select(Appointment).where(Appointment.id == appointment_id)
    )
    appointment = result.scalar_one()
    expires_at = appointment.expires_at
    assert expires_at is not None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    assert expires_at < slot - timedelta(days=4), (
        "la retencion debe durar minutos, no hasta el horario del turno"
    )
    assert appointment.terms_accepted_at is not None


@pytest.mark.asyncio
async def test_manual_booking_notifies_the_store_owner(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El dueño tiene que enterarse de los turnos que debe confirmar a mano."""
    store_public_id, token = await register_and_login(
        client, slug="tienda-aviso", email="aviso@test.com"
    )
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=2)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)
    slot = starts_at.replace(hour=9, minute=0, second=0, microsecond=0)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": slot.isoformat(),
            "client_name": "Cliente WhatsApp",
            "client_phone": "+5491155566666",
            "payment_method": "manual",
            "accepts_terms": True,
            "idempotency_key": "notify-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text

    stats = await process_outbox_batch(test_session)
    assert stats["processed"] >= 1

    result = await test_session.execute(
        select(Notification).where(
            Notification.type == NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value
        )
    )
    notification = result.scalars().first()
    assert notification is not None
    assert "Cliente WhatsApp" in (notification.body or "")

    listing = await client.get("/notifications", headers=auth_headers(token))
    assert listing.status_code == 200, listing.text
    assert listing.json()["unread_count"] >= 1

    read_all = await client.post("/notifications/read-all", headers=auth_headers(token))
    assert read_all.status_code == 200, read_all.text
    assert read_all.json()["unread_count"] == 0


@pytest.mark.asyncio
async def test_reconciliation_total_includes_manually_confirmed_payments(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El total acreditado debe sumar la seña cobrada por fuera, no ignorarla."""
    _stub_preference(monkeypatch)
    store_public_id, token = await register_and_login(
        client, slug="tienda-concilia", email="concilia@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)

    service_public_id = await create_service(
        client,
        token,
        deposit_mode="optional",
        deposit_type="fixed",
        deposit_amount=2500,
    )
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)
    slot = starts_at.replace(hour=15, minute=0, second=0, microsecond=0)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": slot.isoformat(),
            "client_name": "Cliente Manual",
            "client_phone": "+5491155577777",
            "payment_method": "manual",
            "accepts_terms": True,
            "idempotency_key": "manual-confirm-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    appointment_id = cast(str, booking.json()["public_id"])

    confirmed = await client.post(
        f"/payments/{appointment_id}/manual-confirm",
        headers=auth_headers(token),
        json={"amount": 2500, "notes": "Transferencia por WhatsApp"},
    )
    assert confirmed.status_code == 200, confirmed.text

    summary = await client.get(
        "/payments/reconciliation/summary", headers=auth_headers(token)
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["manual_confirmed_payments"] == 1
    assert float(body["total_approved_amount"]) == pytest.approx(2500.0)

    total = await test_session.execute(select(func.count()).select_from(Notification))
    assert total.scalar_one() >= 0
