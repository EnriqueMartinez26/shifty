from __future__ import annotations

import os
import random
import uuid
from datetime import datetime, timedelta, timezone
import hashlib
import hmac

from locust import HttpUser, between, task


STORE_PUBLIC_ID = os.getenv("SHIFTY_STORE_PUBLIC_ID", "")
SERVICE_PUBLIC_ID = os.getenv("SHIFTY_SERVICE_PUBLIC_ID", "")
STAFF_PUBLIC_ID = os.getenv("SHIFTY_STAFF_PUBLIC_ID", "")
STORE_PUBLIC_IDS = [
    value.strip()
    for value in os.getenv("SHIFTY_STORE_PUBLIC_IDS", "").split(",")
    if value.strip()
]
SERVICE_PUBLIC_IDS = [
    value.strip()
    for value in os.getenv("SHIFTY_SERVICE_PUBLIC_IDS", "").split(",")
    if value.strip()
]
STAFF_PUBLIC_IDS = [
    value.strip()
    for value in os.getenv("SHIFTY_STAFF_PUBLIC_IDS", "").split(",")
    if value.strip()
]
BOOKING_PHONE_PREFIX = os.getenv("SHIFTY_BOOKING_PHONE_PREFIX", "+54911")
MERCADOPAGO_WEBHOOK_SECRET = os.getenv("SHIFTY_MERCADOPAGO_WEBHOOK_SECRET", "")


def _tenant_pool() -> list[tuple[str, str, str]]:
    if STORE_PUBLIC_IDS and SERVICE_PUBLIC_IDS and STAFF_PUBLIC_IDS:
        size = min(
            len(STORE_PUBLIC_IDS), len(SERVICE_PUBLIC_IDS), len(STAFF_PUBLIC_IDS)
        )
        return [
            (
                STORE_PUBLIC_IDS[index],
                SERVICE_PUBLIC_IDS[index],
                STAFF_PUBLIC_IDS[index],
            )
            for index in range(size)
        ]
    if STORE_PUBLIC_ID and SERVICE_PUBLIC_ID and STAFF_PUBLIC_ID:
        return [(STORE_PUBLIC_ID, SERVICE_PUBLIC_ID, STAFF_PUBLIC_ID)]
    return []


TENANTS = _tenant_pool()


def _future_date(days: int = 7) -> str:
    target = datetime.now(timezone.utc).date() + timedelta(days=days)
    return target.isoformat()


def _tenant() -> tuple[str, str, str] | None:
    if not TENANTS:
        return None
    return random.choice(TENANTS)


def _webhook_signature_headers(
    *, secret: str, data_id: str, request_id: str, ts: str
) -> dict[str, str]:
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


class PublicAvailabilityUser(HttpUser):
    wait_time = between(0.2, 1.2)

    @task(3)
    def public_availability(self) -> None:
        tenant = _tenant()
        if not tenant:
            return
        store_public_id, service_public_id, _staff_public_id = tenant
        self.client.get(
            "/public/availability",
            params={
                "store_public_id": store_public_id,
                "service_id": service_public_id,
                "date": _future_date(days=random.randint(1, 14)),
            },
            name="/public/availability",
        )

    @task(1)
    def public_booking(self) -> None:
        tenant = _tenant()
        if not tenant:
            return
        store_public_id, service_public_id, staff_public_id = tenant
        starts_at = datetime.now(timezone.utc) + timedelta(
            days=7, hours=random.randint(8, 18)
        )
        payload = {
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "staff_id": staff_public_id,
            "starts_at": starts_at.isoformat(),
            "client_name": "Load Test",
            "client_phone": f"{BOOKING_PHONE_PREFIX}{random.randint(1000000, 9999999)}",
            "client_email": None,
            "idempotency_key": f"load-{uuid.uuid4().hex}",
        }
        self.client.post(
            "/public/appointments", json=payload, name="/public/appointments"
        )


class PublicAbuseUser(HttpUser):
    wait_time = between(0.05, 0.4)

    @task(2)
    def otp_spam_same_subject(self) -> None:
        tenant = _tenant()
        if not tenant:
            return
        store_public_id, _service_public_id, _staff_public_id = tenant
        self.client.post(
            "/public/otp/request",
            json={
                "store_public_id": store_public_id,
                "phone": f"{BOOKING_PHONE_PREFIX}0000000",
                "channel": "whatsapp",
            },
            name="/public/otp/request spam",
        )

    @task(1)
    def self_service_without_otp(self) -> None:
        tenant = _tenant()
        if not tenant:
            return
        store_public_id, _service_public_id, _staff_public_id = tenant
        self.client.get(
            f"/public/client/{store_public_id}/{BOOKING_PHONE_PREFIX}0000000/appointments",
            name="/public/client appointments without otp",
        )


class PaymentsWebhookUser(HttpUser):
    wait_time = between(0.5, 2.0)

    @task
    def webhook_ping(self) -> None:
        tenant = _tenant()
        if not tenant:
            return
        store_public_id, _service_public_id, _staff_public_id = tenant
        data_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        ts = str(int(datetime.now(timezone.utc).timestamp()))
        payload = {"id": str(uuid.uuid4()), "type": "payment", "data": {"id": data_id}}
        headers = (
            _webhook_signature_headers(
                secret=MERCADOPAGO_WEBHOOK_SECRET,
                data_id=data_id,
                request_id=request_id,
                ts=ts,
            )
            if MERCADOPAGO_WEBHOOK_SECRET
            else {}
        )
        self.client.post(
            f"/payments/webhooks/mercadopago?store_id={store_public_id}",
            json=payload,
            headers=headers,
            name="/payments/webhooks/mercadopago",
        )
