"""Suite adversarial: ataca la API como lo haria un cliente hostil o torpe.

Cubre las falencias clasicas: campos sin limite de caracteres, inconsistencias
de mayusculas/minusculas, endpoints que deberian exigir autenticacion, fuga de
datos entre tiendas, cuerpos malformados y montos absurdos. Ninguna de estas
requests debe terminar en un 500: la API tiene que rechazarlas con un error
controlado.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

# ---------------------------------------------------------------------------
# Campos sin limite de caracteres
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_public_booking_fields_are_rejected_not_500(
    client: AsyncClient,
) -> None:
    """Nombres y notas gigantes deben dar 422, nunca un error interno."""
    store_public_id, token = await register_and_login(
        client, slug="tienda-oversize", email="oversize@test.com"
    )
    service_public_id = await create_service(client, token)

    response = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "starts_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "client_name": "A" * 5000,
            "client_phone": "+5491155500000",
            "notes": "N" * 5000,
            "idempotency_key": "oversize-booking-001",
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_oversized_body_is_rejected_by_request_guard(
    client: AsyncClient,
) -> None:
    """Un body mas grande que MAX_REQUEST_BODY_BYTES se corta antes de parsear."""
    response = await client.post(
        "/public/otp/request",
        content=b"{" + b"a" * 40_000 + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413, response.text


@pytest.mark.asyncio
async def test_huge_amounts_do_not_overflow_the_database(
    client: AsyncClient,
) -> None:
    """Montos absurdos deben rebotar en la validacion, no desbordar Numeric(12,2)."""
    _, token = await register_and_login(
        client, slug="tienda-monto", email="monto@test.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200

    response = await client.post(
        "/payments/APPT123/manual-confirm",
        headers=auth_headers(token),
        json={"amount": 10**30},
    )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Mayusculas / minusculas
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_tolerates_email_case_differences(client: AsyncClient) -> None:
    """Registrarse con un email y loguearse con otra capitalizacion debe funcionar."""
    register = await client.post(
        "/auth/register",
        json={
            "store_name": "Tienda Case",
            "store_slug": "tienda-case",
            "business_type": "generic",
            "admin_email": "MiXeD.CaSe@Test.com",
            "admin_password": "Password123!",
            "admin_first_name": "Case",
            "admin_last_name": "Sensitive",
        },
    )
    assert register.status_code == 201, register.text

    for attempt in ("mixed.case@test.com", "MIXED.CASE@TEST.COM"):
        login = await client.post(
            "/auth/login",
            json={"email": attempt, "password": "Password123!"},
        )
        assert login.status_code == 200, f"{attempt}: {login.text}"


@pytest.mark.asyncio
async def test_duplicate_registration_with_different_case_is_rejected(
    client: AsyncClient,
) -> None:
    """El mismo email con otra capitalizacion no puede crear una segunda cuenta."""
    payload = {
        "store_name": "Tienda Dup",
        "store_slug": "tienda-dup",
        "business_type": "generic",
        "admin_email": "dup@test.com",
        "admin_password": "Password123!",
        "admin_first_name": "Dup",
        "admin_last_name": "Uno",
    }
    first = await client.post("/auth/register", json=payload)
    assert first.status_code == 201, first.text

    second = await client.post(
        "/auth/register",
        json={**payload, "store_slug": "tienda-dup-2", "admin_email": "DUP@test.com"},
    )
    assert second.status_code in {400, 409}, second.text


@pytest.mark.asyncio
async def test_staff_email_case_collision_cannot_break_login(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Crear staff con el email del admin en mayusculas debe rechazarse.

    Sin normalizacion quedarian dos usuarios que el login case-insensitive
    matchea a la vez, y ese login pasaria a tirar MultipleResultsFound (500).
    """
    _, token = await register_and_login(
        client, slug="tienda-colision", email="colision@test.com"
    )

    res = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": "Doble",
            "first_name": "Doble",
            "last_name": "Identidad",
            "email": "COLISION@test.com",
            "service_ids": [],
        },
    )
    assert res.status_code in {400, 409, 422}, res.text

    emails = (await test_session.execute(select(User.email))).scalars().all()
    normalized = [e.lower() for e in emails]
    assert normalized.count("colision@test.com") == 1

    login = await client.post(
        "/auth/login",
        json={"email": "colision@test.com", "password": "Password123!"},
    )
    assert login.status_code == 200, login.text


@pytest.mark.asyncio
async def test_public_store_slug_tolerates_uppercase(client: AsyncClient) -> None:
    """La URL publica la tipean humanos: /MiTienda debe resolver a /mitienda."""
    await register_and_login(client, slug="mitienda", email="slugcase@test.com")

    response = await client.get("/public/stores/MiTienda")
    assert response.status_code == 200, response.text
    body = response.json()
    payload = body.get("data", body)
    assert payload["slug"] == "mitienda"


# ---------------------------------------------------------------------------
# Accesos que deben estar cerrados
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_protected_endpoints_reject_anonymous_access(
    client: AsyncClient,
) -> None:
    """Ninguna ruta administrativa puede responder sin token."""
    protected = [
        ("GET", "/payments/gateway-config"),
        ("GET", "/payments/reconciliation/summary"),
        ("POST", "/payments/mercadopago/oauth/start"),
        ("GET", "/notifications"),
        ("POST", "/notifications/read-all"),
        ("GET", "/stores/me"),
        ("GET", "/users/"),
        ("GET", "/reports/summary"),
    ]
    for method, path in protected:
        response = await client.request(method, path)
        assert response.status_code in {401, 403}, (
            f"{method} {path} respondio {response.status_code}: expuesto sin auth"
        )


@pytest.mark.asyncio
async def test_cross_store_data_is_not_readable(client: AsyncClient) -> None:
    """Una tienda no puede leer notificaciones ni turnos de otra."""
    _, token_a = await register_and_login(
        client, slug="tienda-a-cross", email="cross-a@test.com"
    )
    service_a = await create_service(client, token_a)
    staff_a = await create_staff(client, token_a, service_a)
    starts_at = datetime.now(timezone.utc) + timedelta(days=2)
    await add_staff_schedule(client, token_a, staff_a, target_date=starts_at)

    _, token_b = await register_and_login(
        client, slug="tienda-b-cross", email="cross-b@test.com"
    )

    staff_list_b = await client.get("/staff/", headers=auth_headers(token_b))
    assert staff_list_b.status_code == 200
    body = staff_list_b.json()
    staff_items = body.get("data", body) if isinstance(body, dict) else body
    assert staff_items == [], "la tienda B ve el staff de la tienda A"

    notifications_b = await client.get("/notifications", headers=auth_headers(token_b))
    assert notifications_b.status_code == 200
    notif_body = notifications_b.json()
    notif_payload = (
        notif_body.get("data", notif_body)
        if isinstance(notif_body, dict)
        else notif_body
    )
    assert notif_payload["items"] == []


@pytest.mark.asyncio
async def test_client_appointment_listing_requires_otp(client: AsyncClient) -> None:
    """Saber un telefono ajeno no alcanza para ver los turnos de esa persona."""
    store_public_id, _token = await register_and_login(
        client, slug="tienda-otp-guard", email="otp-guard@test.com"
    )
    response = await client.get(
        f"/public/client/{store_public_id}/+5491155511122/appointments"
    )
    assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Cuerpos hostiles y estados invalidos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_with_malformed_json_returns_400_not_500(
    client: AsyncClient,
) -> None:
    for content in (b"{not-json", b"[1,2,3]", b'"just-a-string"'):
        response = await client.post(
            "/payments/webhooks/mercadopago?store_id=whatever",
            content=content,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code < 500, (
            f"payload {content!r} produjo {response.status_code}"
        )


@pytest.mark.asyncio
async def test_webhook_without_signature_is_rejected(client: AsyncClient) -> None:
    store_public_id, token = await register_and_login(
        client, slug="tienda-sinfirma", email="sinfirma@test.com"
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
            "webhook_secret": "secret-demo",
        },
    )
    assert upsert.status_code == 200

    response = await client.post(
        f"/payments/webhooks/mercadopago?store_id={store_public_id}",
        json={"id": "evt-x", "type": "payment", "data": {"id": "pay-x"}},
    )
    assert response.status_code in {400, 401}, response.text


@pytest.mark.asyncio
async def test_refund_of_a_pending_payment_is_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No se puede marcar como reembolsado un cobro que nunca se acredito."""
    import modules.payments.service as payments_service

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": "pref-adversarial",
            "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=1",
        }

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)

    store_public_id, token = await register_and_login(
        client, slug="tienda-refund-guard", email="refund-guard@test.com"
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
        json={"access_token": "TEST-ACCESS-TOKEN-1234567890"},
    )
    assert upsert.status_code == 200

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
    slot = starts_at.replace(hour=14, minute=0, second=0, microsecond=0)

    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": slot.isoformat(),
            "client_name": "Cliente Refund",
            "client_phone": "+5491155533445",
            "payment_method": "mercadopago",
            "accepts_terms": True,
            "idempotency_key": "refund-guard-booking-001",
        },
    )
    assert booking.status_code == 201, booking.text
    payment_public_id = cast(str, booking.json()["payment_public_id"])

    refund = await client.post(
        f"/payments/{payment_public_id}/refund",
        headers=auth_headers(token),
        json={"reason": "intento invalido"},
    )
    assert refund.status_code == 422, refund.text

    status_check = await client.get(
        f"/public/payments/{payment_public_id}/status",
        params={"store_public_id": store_public_id},
    )
    assert status_check.status_code == 200
    body = status_check.json()
    payload = body.get("data", body)
    assert payload["payment_status"] == "pending", "el refund invalido altero el pago"
