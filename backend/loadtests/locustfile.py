from __future__ import annotations

import os
import random
import uuid
from datetime import datetime, timedelta, timezone

from locust import HttpUser, between, task


STORE_PUBLIC_ID = os.getenv("SHIFTY_STORE_PUBLIC_ID", "")
SERVICE_PUBLIC_ID = os.getenv("SHIFTY_SERVICE_PUBLIC_ID", "")
STAFF_PUBLIC_ID = os.getenv("SHIFTY_STAFF_PUBLIC_ID", "")
BOOKING_PHONE_PREFIX = os.getenv("SHIFTY_BOOKING_PHONE_PREFIX", "+54911")


def _future_date(days: int = 7) -> str:
    target = datetime.now(timezone.utc).date() + timedelta(days=days)
    return target.isoformat()


class PublicAvailabilityUser(HttpUser):
    wait_time = between(0.2, 1.2)

    @task(3)
    def public_availability(self):
        if not STORE_PUBLIC_ID or not SERVICE_PUBLIC_ID:
            return
        self.client.get(
            "/public/availability",
            params={
                "store_public_id": STORE_PUBLIC_ID,
                "service_id": SERVICE_PUBLIC_ID,
                "date": _future_date(days=random.randint(1, 14)),
            },
            name="/public/availability",
        )

    @task(1)
    def public_booking(self):
        if not STORE_PUBLIC_ID or not SERVICE_PUBLIC_ID or not STAFF_PUBLIC_ID:
            return
        starts_at = datetime.now(timezone.utc) + timedelta(days=7, hours=random.randint(8, 18))
        payload = {
            "store_public_id": STORE_PUBLIC_ID,
            "service_id": SERVICE_PUBLIC_ID,
            "staff_id": STAFF_PUBLIC_ID,
            "starts_at": starts_at.isoformat(),
            "client_name": "Load Test",
            "client_phone": f"{BOOKING_PHONE_PREFIX}{random.randint(1000000, 9999999)}",
            "client_email": None,
            "idempotency_key": f"load-{uuid.uuid4().hex}",
        }
        self.client.post("/public/appointments", json=payload, name="/public/appointments")


class PaymentsWebhookUser(HttpUser):
    wait_time = between(0.5, 2.0)

    @task
    def webhook_ping(self):
        payload = {"id": str(uuid.uuid4()), "type": "payment", "data": {"id": str(uuid.uuid4())}}
        self.client.post("/payments/webhooks/mercadopago", json=payload, name="/payments/webhooks/mercadopago")
