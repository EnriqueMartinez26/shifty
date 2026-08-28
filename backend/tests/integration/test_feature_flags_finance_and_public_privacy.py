from datetime import datetime, time as dt_time, timedelta, timezone
import hashlib
import hmac
from typing import Any, AsyncIterator, cast

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import settings
from core.utils import local_to_utc
from core.crypto import decrypt_secret
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
import modules.promotions.model
import modules.services.model
import modules.staff.model
import modules.stores.model
import modules.users.model
from modules.payments.model import (
    OutboxMessage,
    Payment,
    PaymentGatewayConfig,
    WebhookInbox,
)
from modules.users.model import User

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    session_local = async_sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_local() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(test_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    settings.ALLOW_PUBLIC_REGISTRATION = True

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield test_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"x-raw-response": "true"},
    ) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


async def register_and_login(
    client: AsyncClient, *, slug: str, email: str
) -> tuple[str, str]:
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
    store_public_id = cast(str, register.json()["store_public_id"])

    login = await client.post(
        "/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    assert login.status_code == 200, login.text
    token = cast(str, login.json()["access_token"])

    # Publicar la politica de sena es requisito para activar cobros online, asi
    # que las tiendas de prueba nacen con una.
    policy = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={
            "deposit_policy": (
                "La sena se descuenta del total y se devuelve con 24hs de aviso."
            )
        },
    )
    assert policy.status_code == 200, policy.text
    return store_public_id, token


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def webhook_signature_headers(
    *, secret: str, data_id: str, request_id: str, ts: str
) -> dict[str, str]:
    ts = str(int(datetime.now(timezone.utc).timestamp()))
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
    return cast(str, res.json()["public_id"])


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
    return cast(str, res.json()["public_id"])


async def add_staff_schedule(
    client: AsyncClient, token: str, staff_public_id: str, *, target_date: datetime
) -> None:
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
async def test_payments_feature_flag_and_webhook_idempotency(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="tienda-payments", email="payments@test.com"
    )

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

    count_result = await test_session.execute(
        select(func.count()).select_from(WebhookInbox)
    )
    assert count_result.scalar_one() == 1


@pytest.mark.asyncio
async def test_mercadopago_oauth_start_and_callback_store_credentials(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, token = await register_and_login(
        client, slug="tienda-oauth", email="oauth@test.com"
    )
    settings.MERCADOPAGO_OAUTH_CLIENT_ID = "client-id-demo"
    settings.MERCADOPAGO_OAUTH_CLIENT_SECRET = "client-secret-demo"
    settings.MERCADOPAGO_OAUTH_REDIRECT_URI = (
        "https://api.shifty.test/payments/mercadopago/oauth/callback"
    )
    settings.MERCADOPAGO_OAUTH_AUTH_URL = "https://auth.mercadopago.com/authorization"

    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200

    start = await client.post(
        "/payments/mercadopago/oauth/start", headers=auth_headers(token)
    )
    assert start.status_code == 200, start.text
    auth_url = start.json()["auth_url"]
    assert "client_id=client-id-demo" in auth_url
    assert "response_type=code" in auth_url
    assert "code_challenge=" in auth_url
    assert "code_challenge_method=S256" in auth_url
    state = auth_url.split("state=")[1].split("&", 1)[0]

    async def fake_exchange(*, code: str, code_verifier: str) -> dict[str, str]:
        assert code == "oauth-code-demo"
        assert code_verifier
        return {
            "access_token": "APP_USR-linked-access-token",
            "refresh_token": "TG-linked-refresh-token",
            "public_key": "APP_USR-linked-public-key",
            "user_id": "123456789",
            "scope": "offline_access payments write",
        }

    monkeypatch.setattr(
        "modules.payments.router.exchange_mercadopago_oauth_code", fake_exchange
    )

    callback = await client.get(
        f"/payments/mercadopago/oauth/callback?code=oauth-code-demo&state={state}"
    )
    assert callback.status_code == 303
    assert "mercadopago=connected" in callback.headers["location"]

    config_result = await test_session.execute(
        select(PaymentGatewayConfig).where(PaymentGatewayConfig.store_id.is_not(None))
    )
    config = config_result.scalar_one()
    assert config.provider == "mercadopago"
    assert config.connection_mode == "oauth"
    assert config.oauth_user_id == "123456789"
    assert config.public_key == "APP_USR-linked-public-key"
    assert (
        decrypt_secret(config.encrypted_access_token) == "APP_USR-linked-access-token"
    )
    assert decrypt_secret(config.encrypted_refresh_token) == "TG-linked-refresh-token"

    visible = await client.get("/payments/gateway-config", headers=auth_headers(token))
    assert visible.status_code == 200
    assert visible.json()["configured"] is True
    assert visible.json()["connection_mode"] == "oauth"
    assert visible.json()["oauth_user_id"] == "123456789"


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(client: AsyncClient) -> None:
    store_public_id, token = await register_and_login(
        client, slug="tienda-payments-bad-signature", email="bad-signature@test.com"
    )

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
async def test_outbox_stats_and_manual_process(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="tienda-outbox", email="outbox@test.com"
    )

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

    stats_before = await client.get(
        "/payments/outbox/stats", headers=auth_headers(token)
    )
    assert stats_before.status_code == 200, stats_before.text
    assert stats_before.json()["pending"] >= 1

    processed = await client.post(
        "/payments/outbox/process?limit=10", headers=auth_headers(token)
    )
    assert processed.status_code == 200, processed.text
    assert processed.json()["processed"] >= 1

    stats_after = await client.get(
        "/payments/outbox/stats", headers=auth_headers(token)
    )
    assert stats_after.status_code == 200
    assert stats_after.json()["pending"] == 0


@pytest.mark.asyncio
async def test_ledger_feature_flag_and_running_balance(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="tienda-ledger", email="ledger@test.com"
    )
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

    summary = await client.get("/ledger/summary", headers=auth_headers(token))
    assert summary.status_code == 200, summary.text
    assert summary.json()["debtors_count"] == 1
    assert summary.json()["total_balance"] == "60.00"


@pytest.mark.asyncio
async def test_public_availability_hides_private_block_reasons(
    client: AsyncClient,
) -> None:
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

    # El horario del staff (09:00-12:00) es hora local argentina. El bloqueo se
    # expresa en UTC, asi que se convierte para que caiga dentro de esa franja:
    # 09:00 ART equivale a 12:00 UTC.
    block_start = local_to_utc(future_date, dt_time(9, 0))
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
async def test_public_booking_requires_otp_when_feature_enabled(
    client: AsyncClient,
) -> None:
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
        "starts_at": starts_at.replace(
            hour=10, minute=0, second=0, microsecond=0
        ).isoformat(),
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
    assert allowed_booking.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_public_client_self_service_requires_recent_otp_and_releases_failed_reschedule_key(
    client: AsyncClient,
) -> None:
    settings.OTP_PROVIDER = "console"
    settings.OTP_DEBUG_EXPOSE_CODE = True

    store_public_id, token = await register_and_login(
        client,
        slug="tienda-self-service-otp",
        email="self-service-otp@test.com",
    )

    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=8)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)

    phone = "+5491177700011"
    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": starts_at.replace(
                hour=10, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Autogestion",
            "client_phone": phone,
            "idempotency_key": "self-service-otp-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text

    blocked_list = await client.get(
        f"/public/client/{store_public_id}/5491177700011/appointments",
    )
    assert blocked_list.status_code == 403

    reschedule_payload = {
        "phone": phone,
        "new_starts_at": starts_at.replace(
            hour=11, minute=0, second=0, microsecond=0
        ).isoformat(),
        "idempotency_key": "self-service-reschedule-otp-001",
    }
    blocked_reschedule = await client.patch(
        f"/public/client/appointments/{booking.json()['public_id']}/reschedule",
        json=reschedule_payload,
    )
    assert blocked_reschedule.status_code == 403

    otp_request = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store_public_id,
            "phone": phone,
            "channel": "whatsapp",
        },
    )
    assert otp_request.status_code == 200, otp_request.text

    otp_verify = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store_public_id,
            "phone": phone,
            "code": otp_request.json()["debug_code"],
        },
    )
    assert otp_verify.status_code == 200, otp_verify.text

    allowed_list = await client.get(
        f"/public/client/{store_public_id}/5491177700011/appointments",
    )
    assert allowed_list.status_code == 200, allowed_list.text
    assert len(allowed_list.json()["appointments"]) == 1

    allowed_reschedule = await client.patch(
        f"/public/client/appointments/{booking.json()['public_id']}/reschedule",
        json=reschedule_payload,
    )
    assert allowed_reschedule.status_code == 200, allowed_reschedule.text
    assert allowed_reschedule.json()["starts_at"].startswith(
        starts_at.date().isoformat()
    )


@pytest.mark.asyncio
async def test_public_booking_allows_missing_email_and_any_professional(
    client: AsyncClient,
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="tienda-any-staff", email="any-staff@test.com"
    )
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=3)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "starts_at": starts_at.replace(
                hour=10, minute=0, second=0, microsecond=0
            ).isoformat(),
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
async def test_create_payment_preference_uses_real_mercadopago_payload_when_gateway_is_configured(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.payments.service as payments_service

    async def fake_mp_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert access_token == "TEST-ACCESS-TOKEN-1234567890"
        assert method == "POST"
        assert path == "/checkout/preferences"
        assert json_body is not None
        return {
            "id": "real-pref-123",
            "init_point": "https://www.mercadopago.com/checkout/v1/redirect?pref=real-prod",
            "sandbox_init_point": "https://sandbox.mercadopago.com/checkout/v1/redirect?pref=real-sandbox",
        }

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_mp_request)

    store_public_id, token = await register_and_login(
        client, slug="tienda-real-link", email="real-link@test.com"
    )
    assert store_public_id

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
        deposit_type="percent",
        deposit_amount=30,
    )
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=3)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": starts_at.replace(
                hour=10, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Pago Real",
            "client_phone": "+5491155511111",
            "payment_method": "mercadopago",
            "idempotency_key": "real-link-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    body = booking.json()
    assert body["payment_link"].startswith("https://www.mercadopago.com/")
    assert body["payment_status"] == "pending"


@pytest.mark.asyncio
async def test_webhook_can_fetch_mercadopago_payment_details_when_notification_is_minimal(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.payments.processing as payments_processing
    import modules.payments.service as payments_service

    async def fake_create_preference(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": "pref-webhook-fetch",
            "sandbox_init_point": "https://sandbox.mercadopago.com/checkout/v1/redirect?pref=fetch",
        }

    async def fake_fetch_payment(
        db: AsyncSession, *, store_id: str, payment_id: str
    ) -> dict[str, Any]:
        assert payment_id == "mp-pay-minimal-123"
        assert store_id
        assert db
        return {
            "id": payment_id,
            "status": "approved",
            "external_reference": booking_public_id,
            "metadata": {"appointment_id": booking_public_id},
            "date_approved": datetime.now(timezone.utc).isoformat(),
        }

    monkeypatch.setattr(
        payments_service, "_mercadopago_api_request", fake_create_preference
    )
    store_public_id, token = await register_and_login(
        client, slug="tienda-webhook-fetch", email="webhook-fetch@test.com"
    )
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
        deposit_amount=2000,
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
            "starts_at": starts_at.replace(
                hour=13, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Webhook Fetch",
            "client_phone": "+5491144499999",
            "payment_method": "mercadopago",
            "idempotency_key": "webhook-fetch-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text

    booking_public_id = booking.json()["public_id"]
    monkeypatch.setattr(
        payments_processing, "fetch_mercadopago_payment", fake_fetch_payment
    )

    payload = {
        "id": "evt-fetch-123",
        "type": "payment",
        "data": {"id": "mp-pay-minimal-123"},
    }
    signature_headers = webhook_signature_headers(
        secret="secret-demo",
        data_id="mp-pay-minimal-123",
        request_id="req-fetch-123",
        ts="1710001111",
    )
    webhook = await client.post(
        f"/payments/webhooks/mercadopago?store_id={store_public_id}",
        json=payload,
        headers=signature_headers,
    )
    assert webhook.status_code == 200, webhook.text

    appointment_search = await client.get(
        "/appointments/search?page=1&page_size=10", headers=auth_headers(token)
    )
    refreshed = next(
        item
        for item in appointment_search.json()["results"]
        if item["public_id"] == booking_public_id
    )
    assert refreshed["status"] == "confirmed"


@pytest.mark.asyncio
async def test_public_booking_can_apply_store_promotion_and_reduce_payment_amount(
    client: AsyncClient,
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="tienda-promos", email="promos@test.com"
    )

    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200, flags.text

    promo = await client.post(
        "/promotions/",
        headers=auth_headers(token),
        json={
            "code": "BIENVENIDA20",
            "title": "Promo bienvenida",
            "promotion_type": "fixed",
            "value": "2000.00",
            "is_active": True,
        },
    )
    assert promo.status_code == 201, promo.text

    service_public_id = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=50,
    )
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)

    preview = await client.get(
        "/public/promotions/preview",
        params={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "code": "BIENVENIDA20",
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["discount_amount"] == 2000.0
    assert preview.json()["final_amount"] == 8000.0

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": starts_at.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Promo",
            "client_phone": "+5491166600000",
            "promotion_code": "BIENVENIDA20",
            "idempotency_key": "promotion-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    body = booking.json()
    assert body["promotion_code"] == "BIENVENIDA20"
    assert body["service_price"] == 10000.0
    assert body["discount_amount"] == 2000.0
    assert body["final_price"] == 8000.0
    assert body["payment_amount"] == 4000.0

    promotions = await client.get("/promotions/", headers=auth_headers(token))
    assert promotions.status_code == 200, promotions.text
    current = next(item for item in promotions.json() if item["code"] == "BIENVENIDA20")
    assert current["current_uses"] == 1


@pytest.mark.asyncio
async def test_public_booking_persists_configured_custom_fields(
    client: AsyncClient,
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="tienda-intake", email="intake@test.com"
    )
    settings_update = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={
            "custom_client_fields": [
                {
                    "key": "motivo_consulta",
                    "label": "Motivo de consulta",
                    "type": "text",
                    "required": True,
                    "placeholder": "Contanos brevemente",
                    "options": [],
                },
                {
                    "key": "tipo_visita",
                    "label": "Tipo de visita",
                    "type": "select",
                    "required": False,
                    "options": [
                        {"label": "Primera vez", "value": "primera_vez"},
                        {"label": "Control", "value": "control"},
                    ],
                },
            ]
        },
    )
    assert settings_update.status_code == 200, settings_update.text
    assert len(settings_update.json()["custom_client_fields"]) == 2

    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=3)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": starts_at.replace(
                hour=10, minute=30, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Intake",
            "client_phone": "+5491170010020",
            "custom_fields": {
                "motivo_consulta": "Control anual",
                "tipo_visita": "control",
            },
            "idempotency_key": "intake-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    assert booking.json()["custom_fields"]["motivo_consulta"] == "Control anual"

    appointments = await client.get(
        "/appointments/search?page=1&page_size=10", headers=auth_headers(token)
    )
    assert appointments.status_code == 200, appointments.text
    stored = next(
        item
        for item in appointments.json()["results"]
        if item["public_id"] == booking.json()["public_id"]
    )
    assert stored["intake_answers"]["tipo_visita"] == "control"


@pytest.mark.asyncio
async def test_manual_refund_and_reconciliation_summary(
    client: AsyncClient,
) -> None:
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
            "starts_at": starts_at.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
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
async def test_manual_confirm_sets_appointment_confirmed_when_payment_exists(
    client: AsyncClient,
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="tienda-manual-confirm", email="manual-confirm@test.com"
    )
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
            "starts_at": starts_at.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Manual",
            "client_phone": "+5491133344455",
            "idempotency_key": "manual-confirm-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    assert booking.json()["status"] == "pending"

    manual_confirm = await client.post(
        f"/payments/{booking.json()['public_id']}/manual-confirm",
        headers=auth_headers(token),
        json={"amount": "3000.00"},
    )
    assert manual_confirm.status_code == 200, manual_confirm.text
    assert manual_confirm.json()["status"] == "manual_confirmed"

    appointment_search = await client.get(
        "/appointments/search?page=1&page_size=10", headers=auth_headers(token)
    )
    assert appointment_search.status_code == 200, appointment_search.text
    refreshed = next(
        item
        for item in appointment_search.json()["results"]
        if item["public_id"] == booking.json()["public_id"]
    )
    assert refreshed["status"] == "confirmed"


@pytest.mark.asyncio
async def test_payment_webhook_approves_pending_booking_and_confirms_turn(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.payments.service as payments_service

    async def fake_mp_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert access_token
        assert method
        assert path
        assert json_body is None or isinstance(json_body, dict)
        return {
            "id": "pref-webhook-booking",
            "sandbox_init_point": "https://sandbox.mercadopago.com/checkout/v1/redirect?pref=booking",
        }

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_mp_request)
    store_public_id, token = await register_and_login(
        client, slug="tienda-webhook-booking", email="webhook-booking@test.com"
    )
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
            "starts_at": starts_at.replace(
                hour=12, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Webhook",
            "client_phone": "+5491122200011",
            "payment_method": "mercadopago",
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

    appointment_search = await client.get(
        "/appointments/search?page=1&page_size=10", headers=auth_headers(token)
    )
    refreshed = next(
        item
        for item in appointment_search.json()["results"]
        if item["public_id"] == booking.json()["public_id"]
    )
    assert refreshed["status"] == "confirmed"

    public_status = await client.get(
        f"/public/payments/{payment.id}/status",
        params={"store_public_id": store_public_id},
    )
    assert public_status.status_code == 200, public_status.text
    assert public_status.json()["payment_status"] == "approved"
    assert public_status.json()["appointment_status"] == "confirmed"


@pytest.mark.asyncio
async def test_public_booking_releases_idempotency_and_rolls_back_when_payment_provider_fails(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.payments.service as payments_service

    async def failing_mp_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert access_token
        assert method
        assert path
        assert json_body is None or isinstance(json_body, dict)
        raise RuntimeError("timeout upstream")

    async def successful_mp_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert access_token
        assert method
        assert path
        assert json_body is None or isinstance(json_body, dict)
        return {
            "id": "pref-retry-ok",
            "sandbox_init_point": "https://sandbox.mercadopago.com/checkout/v1/redirect?pref=retry-ok",
        }

    monkeypatch.setattr(
        payments_service, "_mercadopago_api_request", failing_mp_request
    )

    store_public_id, token = await register_and_login(
        client,
        slug="tienda-provider-failure",
        email="provider-failure@test.com",
    )

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

    booking_payload = {
        "store_public_id": store_public_id,
        "service_id": service_public_id,
        "staff_id": staff_public_id,
        "starts_at": starts_at.replace(
            hour=12, minute=30, second=0, microsecond=0
        ).isoformat(),
        "client_name": "Cliente Retry",
        "client_phone": "+5491122299988",
        "payment_method": "mercadopago",
        "idempotency_key": "provider-failure-booking-001",
    }

    failed_booking = await client.post("/public/appointments", json=booking_payload)
    assert failed_booking.status_code == 502, failed_booking.text

    appointment_count = await test_session.scalar(
        select(func.count()).select_from(modules.appointments.model.Appointment)
    )
    payment_count = await test_session.scalar(select(func.count()).select_from(Payment))
    assert appointment_count == 0
    assert payment_count == 0

    monkeypatch.setattr(
        payments_service, "_mercadopago_api_request", successful_mp_request
    )

    retried_booking = await client.post("/public/appointments", json=booking_payload)
    assert retried_booking.status_code == 201, retried_booking.text
    assert retried_booking.json()["payment_link"].startswith(
        "https://sandbox.mercadopago.com/"
    )

    appointment_count = await test_session.scalar(
        select(func.count()).select_from(modules.appointments.model.Appointment)
    )
    payment_count = await test_session.scalar(select(func.count()).select_from(Payment))
    assert appointment_count == 1
    assert payment_count == 1


@pytest.mark.asyncio
async def test_professional_can_access_own_reports_only(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="tienda-reports-pro", email="reports-pro@test.com"
    )
    assert store_public_id
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=7)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)

    user_result = await test_session.execute(
        select(User).where(User.id == staff_public_id)
    )
    professional_user = user_result.scalar_one()
    professional_user.hashed_password = hash_password("StaffPass123!")
    await test_session.commit()

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": starts_at.replace(
                hour=15, minute=0, second=0, microsecond=0
            ).isoformat(),
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


@pytest.mark.asyncio
async def test_report_summary_includes_client_service_and_debt_metrics(
    client: AsyncClient,
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="tienda-reportes-full", email="reportes-full@test.com"
    )
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": starts_at.replace(
                hour=14, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Reporte Full",
            "client_phone": "+5491199980011",
            "idempotency_key": "report-full-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text

    search = await client.get(
        "/appointments/search?page=1&page_size=10", headers=auth_headers(token)
    )
    assert search.status_code == 200, search.text
    client_id = next(
        item
        for item in search.json()["results"]
        if item["public_id"] == booking.json()["public_id"]
    )["client_id"]

    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"ledger": True},
    )
    assert flags.status_code == 200, flags.text

    charge = await client.post(
        f"/ledger/customers/{client_id}/movements",
        headers=auth_headers(token),
        json={
            "movement_type": "charge",
            "amount": "100.00",
            "notes": "Saldo pendiente",
        },
    )
    assert charge.status_code == 200, charge.text

    summary = await client.get(
        f"/reports/summary?from_date={starts_at.date().isoformat()}&to_date={starts_at.date().isoformat()}",
        headers=auth_headers(token),
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["client_stats"]["total_clients"] == 1
    assert body["top_services"][0]["service_id"] == service_public_id
    assert body["top_clients"][0]["client_id"] == client_id
    assert body["debt_summary"]["debtors_count"] == 1
    assert body["debt_summary"]["outstanding_balance"] == 100.0


@pytest.mark.asyncio
async def test_pending_whatsapp_booking_expires_when_hold_deadline_passes(
    client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    from modules.payments.jobs import expire_unpaid_appointments

    store_public_id, token = await register_and_login(
        client, slug="tienda-whatsapp-expiry", email="whatsapp-expiry@test.com"
    )
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=2)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": starts_at.replace(
                hour=10, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente WhatsApp",
            "client_phone": "+5491112345678",
            "payment_method": "manual",
            "idempotency_key": "whatsapp-expiry-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    assert booking.json()["status"] == "pending"

    result = await test_session.execute(
        select(modules.appointments.model.Appointment).where(
            modules.appointments.model.Appointment.id == booking.json()["public_id"]
        )
    )
    appointment = result.scalar_one()
    appointment.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await test_session.commit()

    expired = await expire_unpaid_appointments(test_session)
    await test_session.refresh(appointment)
    assert expired["expired"] == 1
    assert appointment.status == "expired"


@pytest.mark.asyncio
async def test_store_owner_can_release_pending_mercadopago_booking(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.payments.service as payments_service

    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def fake_mp_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert access_token
        calls.append((method, path, json_body))
        if method == "POST":
            return {
                "id": "pref-owner-release",
                "sandbox_init_point": (
                    "https://sandbox.mercadopago.com/checkout/v1/redirect"
                    "?pref=owner-release"
                ),
            }
        assert method == "PUT"
        assert path == "/checkout/preferences/pref-owner-release"
        assert json_body and json_body["expires"] is True
        assert json_body["expiration_date_to"]
        return {"id": "pref-owner-release", "expires": True}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_mp_request)
    store_public_id, token = await register_and_login(
        client, slug="tienda-owner-release", email="owner-release@test.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200, flags.text
    gateway = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={"access_token": "TEST-OWNER-RELEASE-TOKEN"},
    )
    assert gateway.status_code == 200, gateway.text

    service_public_id = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="fixed",
        deposit_amount=2500,
    )
    staff_public_id = await create_staff(client, token, service_public_id)
    starts_at = datetime.now(timezone.utc) + timedelta(days=3)
    await add_staff_schedule(client, token, staff_public_id, target_date=starts_at)
    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": starts_at.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Release",
            "client_phone": "+5491188877766",
            "payment_method": "mercadopago",
            "idempotency_key": "owner-release-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    assert booking.json()["status"] == "pending_payment"

    release = await client.patch(
        f"/appointments/{booking.json()['public_id']}/release",
        headers=auth_headers(token),
    )
    assert release.status_code == 200, release.text
    assert release.json()["status"] == "expired"
    assert [call[0] for call in calls] == ["POST", "PUT"]

    payment_result = await test_session.execute(
        select(Payment).where(Payment.appointment_id == booking.json()["public_id"])
    )
    assert payment_result.scalar_one().status == "expired"
