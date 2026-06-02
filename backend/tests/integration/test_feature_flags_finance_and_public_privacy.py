from datetime import datetime, timedelta, timezone
import hashlib
import hmac

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import settings
from core.database import get_db
from core.models import Base
from core.security import hash_password
from main import app
import modules.appointments.model
import modules.audit.model
import modules.auth.session_model
import modules.budget.model
import modules.ledger.model
import modules.otp.model
import modules.payments.model
import modules.services.model
import modules.staff.model
import modules.stores.model
import modules.users.model
from modules.payments.model import OutboxMessage, Payment, WebhookInbox
from modules.users.model import User

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine):
    session_local = async_sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_local() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(test_session):
    settings.ALLOW_PUBLIC_REGISTRATION = True

    async def override_get_db():
        yield test_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


async def register_and_login(client: AsyncClient, *, slug: str, email: str) -> tuple[str, str]:
    register = await client.post(
        "/auth/register",
        json={
            "store_name": f"Tienda {slug}",
            "store_slug": slug,
            "admin_email": email,
            "admin_password": "Password123!",
            "admin_first_name": "Admin",
            "admin_last_name": "Demo",
        },
    )
    assert register.status_code == 201, register.text
    store_public_id = register.json()["store_public_id"]

    login = await client.post(
        "/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return store_public_id, token


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def webhook_signature_headers(*, secret: str, data_id: str, request_id: str, ts: str) -> dict[str, str]:
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    digest = hmac.new(
        secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "x-request-id": request_id,
        "x-signature": f"ts={ts},v1={digest}",
    }


async def create_service(
    client: AsyncClient,
    token: str,
    *,
    deposit_mode: str = "none",
    deposit_type: str = "percent",
    deposit_amount: int | None = None,
) -> str:
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={
            "name": "Consulta",
            "duration_minutes": 30,
            "price": 10000,
            "deposit_mode": deposit_mode,
            "deposit_type": deposit_type,
            "deposit_amount": deposit_amount,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["public_id"]


async def create_staff(client: AsyncClient, token: str, service_public_id: str) -> str:
    res = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": "Pro Demo",
            "first_name": "Pro",
            "last_name": "Demo",
            "email": "pro-demo@test.com",
            "service_ids": [service_public_id],
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["public_id"]


async def add_staff_schedule(client: AsyncClient, token: str, staff_public_id: str, *, target_date: datetime) -> None:
    res = await client.post(
        f"/staff/{staff_public_id}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": target_date.weekday(),
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_payments_feature_flag_and_webhook_idempotency(client: AsyncClient, test_session):
    store_public_id, token = await register_and_login(client, slug="tienda-payments", email="payments@test.com")

    blocked = await client.get("/payments/gateway-config", headers=auth_headers(token))
    assert blocked.status_code == 403

    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200
    assert flags.json()["flags"]["payments"] is True

    upsert = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={
            "access_token": "TEST-ACCESS-TOKEN-1234567890",
            "public_key": "TEST-PUBLIC-KEY",
            "webhook_secret": "secret-demo",
        },
    )
    assert upsert.status_code == 200, upsert.text
    assert upsert.json()["configured"] is True
    assert upsert.json()["access_token_masked"] == "********"

    visible = await client.get("/payments/gateway-config", headers=auth_headers(token))
    assert visible.status_code == 200
    assert visible.json()["access_token_masked"] == "********"
    assert "TEST-ACCESS-TOKEN" not in str(visible.json())

    payload = {"id": "evt-123", "type": "payment", "data": {"id": "payment-123"}}
    signature_headers = webhook_signature_headers(
        secret="secret-demo",
        data_id="payment-123",
        request_id="req-123",
        ts="1710000000",
    )
    first = await client.post(
        f"/payments/webhooks/mercadopago?store_id={store_public_id}",
        json=payload,
        headers=signature_headers,
    )
    second = await client.post(
        f"/payments/webhooks/mercadopago?store_id={store_public_id}",
        json=payload,
        headers=signature_headers,
    )
    assert first.status_code == 200
    assert second.status_code == 200

    count_result = await test_session.execute(select(func.count()).select_from(WebhookInbox))
    assert count_result.scalar_one() == 1


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(client: AsyncClient):
    store_public_id, token = await register_and_login(client, slug="tienda-payments-bad-signature", email="bad-signature@test.com")

    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200

    upsert = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={
            "access_token": "TEST-ACCESS-TOKEN-1234567890",
            "public_key": "TEST-PUBLIC-KEY",
            "webhook_secret": "secret-demo",
        },
    )
    assert upsert.status_code == 200

    payload = {"id": "evt-999", "type": "payment", "data": {"id": "payment-999"}}
    bad_headers = {
        "x-request-id": "req-bad-signature",
        "x-signature": "ts=1710000000,v1=deadbeef",
    }

    webhook = await client.post(
        f"/payments/webhooks/mercadopago?store_id={store_public_id}",
        json=payload,
        headers=bad_headers,
    )
    assert webhook.status_code == 401


@pytest.mark.asyncio
async def test_outbox_stats_and_manual_process(client: AsyncClient, test_session):
    _, token = await register_and_login(client, slug="tienda-outbox", email="outbox@test.com")

    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200

    me = await client.get("/me", headers=auth_headers(token))
    assert me.status_code == 200
    store_id = me.json()["store_id"]

    outbox = OutboxMessage(
        store_id=store_id,
        event_type="noop",
        payload={"hello": "world"},
    )
    test_session.add(outbox)
    await test_session.commit()

    stats_before = await client.get("/payments/outbox/stats", headers=auth_headers(token))
    assert stats_before.status_code == 200, stats_before.text
    assert stats_before.json()["pending"] >= 1

    processed = await client.post("/payments/outbox/process?limit=10", headers=auth_headers(token))
    assert processed.status_code == 200, processed.text
    assert processed.json()["processed"] >= 1

    stats_after = await client.get("/payments/outbox/stats", headers=auth_headers(token))
    assert stats_after.status_code == 200
    assert stats_after.json()["pending"] == 0


@pytest.mark.asyncio
async def test_ledger_feature_flag_and_running_balance(client: AsyncClient):
    _, token = await register_and_login(client, slug="tienda-ledger", email="ledger@test.com")
    client_id = "CLIENTE-001"

    blocked = await client.post(
        f"/ledger/customers/{client_id}/movements",
        headers=auth_headers(token),
        json={"movement_type": "charge", "amount": "100.00"},
    )
    assert blocked.status_code == 403

    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"ledger": True},
    )
    assert flags.status_code == 200
    assert flags.json()["flags"]["ledger"] is True

    charge = await client.post(
        f"/ledger/customers/{client_id}/movements",
        headers=auth_headers(token),
        json={"movement_type": "charge", "amount": "100.00", "notes": "Servicio fiado"},
    )
    assert charge.status_code == 200, charge.text
    assert charge.json()["balance_after"] == "100.00"

    payment = await client.post(
        f"/ledger/customers/{client_id}/movements",
        headers=auth_headers(token),
        json={"movement_type": "payment", "amount": "40.00"},
    )
    assert payment.status_code == 200, payment.text
    assert payment.json()["balance_after"] == "60.00"

    ledger = await client.get(
        f"/ledger/customers/{client_id}",
        headers=auth_headers(token),
    )
    assert ledger.status_code == 200
    body = ledger.json()
    assert body["balance"] == "60.00"
    assert len(body["movements"]) == 2


@pytest.mark.asyncio
async def test_public_availability_hides_private_block_reasons(client: AsyncClient):
    store_public_id, token = await register_and_login(
        client, slug="tienda-privacy", email="privacy@test.com"
    )

    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)

    future_date = datetime.now(timezone.utc).date() + timedelta(days=7)
    day_of_week = future_date.weekday()

    schedule = await client.post(
        f"/staff/{staff_public_id}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": day_of_week,
            "start_time": "09:00:00",
            "end_time": "12:00:00",
        },
    )
    assert schedule.status_code == 200, schedule.text

    block_start = datetime(
        future_date.year, future_date.month, future_date.day, 9, 0, tzinfo=timezone.utc
    )
    block_end = block_start + timedelta(hours=1)
    block = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff_public_id,
            "starts_at": block_start.isoformat(),
            "ends_at": block_end.isoformat(),
            "reason": "Vacaciones privadas",
        },
    )
    assert block.status_code == 201, block.text

    availability = await client.get(
        "/public/availability",
        params={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "date": future_date.isoformat(),
        },
    )
    assert availability.status_code == 200, availability.text
    slots = availability.json()
    assert isinstance(slots, list)
    assert slots, "Se esperaban slots de disponibilidad para validar privacidad"

    blocked_slots = [slot for slot in slots if slot["status"] == "blocked"]
    assert blocked_slots, "Se esperaba al menos un slot bloqueado"
    assert all(slot.get("reason") != "Vacaciones privadas" for slot in blocked_slots)
    assert any(slot.get("reason") == "No disponible" for slot in blocked_slots)


@pytest.mark.asyncio
async def test_public_booking_requires_otp_when_feature_enabled(client: AsyncClient):
    settings.OTP_PROVIDER = "console"
    settings.OTP_DEBUG_EXPOSE_CODE = True

    store_public_id, token = await register_and_login(
        client, slug="tienda-otp", email="otp@test.com"
    )

    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"otp_booking": True},
    )
    assert flags.status_code == 200, flags.text
    assert flags.json()["flags"]["otp_booking"] is True

    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)
    booking_payload = {
        "store_public_id": store_public_id,
        "service_id": service_public_id,
        "staff_id": staff_public_id,
        "starts_at": starts_at.replace(hour=10, minute=0, second=0, microsecond=0).isoformat(),
        "client_name": "Cliente OTP",
        "client_phone": "+5491123456789",
        "idempotency_key": "otp-booking-test-001",
    }

    blocked_booking = await client.post("/public/appointments", json=booking_payload)
    assert blocked_booking.status_code == 403

    otp_request = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store_public_id,
            "phone": "+5491123456789",
            "channel": "whatsapp",
        },
    )
    assert otp_request.status_code == 200, otp_request.text
    code = otp_request.json()["debug_code"]

    otp_verify = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store_public_id,
            "phone": "+5491123456789",
            "code": code,
        },
    )
    assert otp_verify.status_code == 200, otp_verify.text

    allowed_booking = await client.post("/public/appointments", json=booking_payload)
    assert allowed_booking.status_code == 201, allowed_booking.text
    assert allowed_booking.json()["status"] in {"confirmed", "pending_payment"}


@pytest.mark.asyncio
async def test_public_booking_allows_missing_email_and_any_professional(client: AsyncClient):
    store_public_id, token = await register_and_login(client, slug="tienda-any-staff", email="any-staff@test.com")
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=3)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "starts_at": starts_at.replace(hour=10, minute=0, second=0, microsecond=0).isoformat(),
            "client_name": "Cliente Any",
            "client_phone": "+5491166667777",
            "idempotency_key": "any-professional-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    body = booking.json()
    assert body["staff_id"] == staff_public_id
    assert body["client_phone"] == "5491166667777"


@pytest.mark.asyncio
async def test_manual_refund_and_reconciliation_summary(client: AsyncClient):
    store_public_id, token = await register_and_login(
        client, slug="tienda-refund", email="refund@test.com"
    )
    assert store_public_id

    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200, flags.text

    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)

    booking = await client.post(
        "/public/appointments",
        json={
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": starts_at.replace(hour=11, minute=0, second=0, microsecond=0).isoformat(),
            "client_name": "Cliente Refund",
            "client_phone": "+5491188877766",
            "idempotency_key": "refund-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    appointment_public_id = booking.json()["public_id"]

    manual_confirm = await client.post(
        f"/payments/{appointment_public_id}/manual-confirm",
        headers=auth_headers(token),
        json={"amount": "5000.00"},
    )
    assert manual_confirm.status_code == 200, manual_confirm.text
    payment_public_id = manual_confirm.json()["public_id"]
    assert manual_confirm.json()["status"] == "manual_confirmed"

    refund = await client.post(
        f"/payments/{payment_public_id}/refund",
        headers=auth_headers(token),
        json={"amount": "5000.00", "reason": "Anulacion", "manual": True},
    )
    assert refund.status_code == 200, refund.text
    assert refund.json()["status"] == "refunded"

    reconciliation = await client.get(
        "/payments/reconciliation/summary",
        headers=auth_headers(token),
    )
    assert reconciliation.status_code == 200, reconciliation.text
    body = reconciliation.json()
    assert body["refunded_payments"] >= 1


@pytest.mark.asyncio
async def test_manual_confirm_sets_appointment_confirmed_when_payment_exists(client: AsyncClient):
    store_public_id, token = await register_and_login(client, slug="tienda-manual-confirm", email="manual-confirm@test.com")
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200, flags.text

    service_public_id = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": starts_at.replace(hour=11, minute=0, second=0, microsecond=0).isoformat(),
            "client_name": "Cliente Manual",
            "client_phone": "+5491133344455",
            "idempotency_key": "manual-confirm-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    assert booking.json()["status"] == "pending_payment"

    manual_confirm = await client.post(
        f"/payments/{booking.json()['public_id']}/manual-confirm",
        headers=auth_headers(token),
        json={"amount": "3000.00"},
    )
    assert manual_confirm.status_code == 200, manual_confirm.text
    assert manual_confirm.json()["status"] == "manual_confirmed"

    appointment_search = await client.get("/appointments/search?page=1&page_size=10", headers=auth_headers(token))
    assert appointment_search.status_code == 200, appointment_search.text
    refreshed = next(item for item in appointment_search.json()["results"] if item["public_id"] == booking.json()["public_id"])
    assert refreshed["status"] == "confirmed"


@pytest.mark.asyncio
async def test_payment_webhook_approves_pending_booking_and_confirms_turn(client: AsyncClient, test_session):
    store_public_id, token = await register_and_login(client, slug="tienda-webhook-booking", email="webhook-booking@test.com")
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200, flags.text

    upsert = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={
            "access_token": "TEST-ACCESS-TOKEN-1234567890",
            "public_key": "TEST-PUBLIC-KEY",
            "webhook_secret": "secret-demo",
        },
    )
    assert upsert.status_code == 200, upsert.text

    service_public_id = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="fixed",
        deposit_amount=2500,
    )
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": starts_at.replace(hour=12, minute=0, second=0, microsecond=0).isoformat(),
            "client_name": "Cliente Webhook",
            "client_phone": "+5491122200011",
            "idempotency_key": "webhook-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    assert booking.json()["status"] == "pending_payment"

    payment_result = await test_session.execute(
        select(Payment).where(Payment.appointment_id == booking.json()["public_id"])
    )
    payment = payment_result.scalar_one()

    payload = {
        "id": "evt-booking-123",
        "type": "payment",
        "data": {
            "id": "mp-pay-123",
            "status": "approved",
            "preference_id": payment.preference_id,
            "metadata": {"appointment_id": booking.json()["public_id"]},
        },
    }
    signature_headers = webhook_signature_headers(
        secret="secret-demo",
        data_id="mp-pay-123",
        request_id="req-booking-123",
        ts="1710000001",
    )
    webhook = await client.post(
        f"/payments/webhooks/mercadopago?store_id={store_public_id}",
        json=payload,
        headers=signature_headers,
    )
    assert webhook.status_code == 200, webhook.text

    appointment_search = await client.get("/appointments/search?page=1&page_size=10", headers=auth_headers(token))
    refreshed = next(item for item in appointment_search.json()["results"] if item["public_id"] == booking.json()["public_id"])
    assert refreshed["status"] == "confirmed"


@pytest.mark.asyncio
async def test_professional_can_access_own_reports_only(client: AsyncClient, test_session):
    store_public_id, token = await register_and_login(client, slug="tienda-reports-pro", email="reports-pro@test.com")
    assert store_public_id
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=7)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)

    user_result = await test_session.execute(select(User).where(User.id == staff_public_id))
    professional_user = user_result.scalar_one()
    professional_user.hashed_password = hash_password("StaffPass123!")
    await test_session.commit()

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": starts_at.replace(hour=15, minute=0, second=0, microsecond=0).isoformat(),
            "client_name": "Cliente Reportes",
            "client_phone": "+5491199988877",
            "idempotency_key": "professional-reports-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text

    login = await client.post(
        "/auth/login",
        json={"email": "pro-demo@test.com", "password": "StaffPass123!"},
    )
    assert login.status_code == 200, login.text
    professional_token = login.json()["access_token"]

    from_date = starts_at.date().isoformat()
    to_date = starts_at.date().isoformat()

    summary = await client.get(
        f"/reports/summary?from_date={from_date}&to_date={to_date}",
        headers=auth_headers(professional_token),
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["stats"]["total_appointments"] == 1

    professionals = await client.get(
        f"/reports/professionals?from_date={from_date}&to_date={to_date}",
        headers=auth_headers(professional_token),
    )
    assert professionals.status_code == 200, professionals.text
    body = professionals.json()
    assert len(body["professionals"]) == 1
    assert body["professionals"][0]["staff_id"] == staff_public_id
