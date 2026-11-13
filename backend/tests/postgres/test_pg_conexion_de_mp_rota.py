"""Varias reservas que se topan a la vez con el refresh rechazado marcan la
conexion de MP UNA vez y avisan al dueno UNA vez, con RLS real (issue #279).

Cada reserva lee la config sin marca, sale a MP sin transaccion abierta
(regla 5), recibe el 401, pide el refresh y MP lo rechaza. La guarda es el
UPDATE condicional (``connection_broken_at IS NULL``): solo la que cambia la
fila publica el aviso al outbox. Bajo RLS el UPDATE corre con el contexto de
la tienda reaplicado; sin eso tocaria 0 filas y no marcaria nada.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.config import settings
from core.crypto import encrypt_secret
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.postgres.test_pg_lotes_skip_locked import _tienda_con_mercadopago

pytestmark = pytest.mark.postgres

CUANTAS = 4
DEMORA_MP = 1.0


@pytest.mark.asyncio
async def test_rafaga_con_refresh_rechazado_marca_y_avisa_una_sola_vez(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        settings, "MERCADOPAGO_OAUTH_REDIRECT_URI", "https://api.test/callback"
    )

    async def api(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise payments_service.MercadoPagoAPIError("vencido", status_code=401)

    async def enviar(method: str, url: str, **_: Any) -> httpx.Response:
        # Lento: todas las reservas llegan al rechazo con la config sin marca.
        await asyncio.sleep(DEMORA_MP)
        return httpx.Response(
            400, json={"error": "invalid_grant"}, request=httpx.Request(method, url)
        )

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", api)
    monkeypatch.setattr(payments_service, "_send_to_mercadopago", enviar)

    store, token = await _tienda_con_mercadopago(client, app_sessions, "mp-rota-pg")
    service = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, service, email="pro-mp-rota@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "update payment_gateway_configs set connection_mode = 'oauth', "
                "encrypted_refresh_token = :refresh"
            ),
            {"refresh": encrypt_secret("REFRESH-PG-1")},
        )

    def reservar(i: int) -> Any:
        return client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": service,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=10 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": f"Cliente {i}",
                "client_phone": f"+54911566{i:05d}",
                "client_email": f"c54911566{i:05d}@example.com",
                "payment_method": "auto",
                "accepts_terms": True,
                "idempotency_key": f"mp-rota-pg-{i:06d}",
            },
        )

    respuestas = await asyncio.gather(*(reservar(i) for i in range(CUANTAS)))

    # Cada una falla como hoy (502) y se compensa: ningun turno queda.
    assert [r.status_code for r in respuestas] == [502] * CUANTAS, [
        r.text for r in respuestas
    ]
    async with owner_engine.connect() as conn:
        marcas = (
            await conn.execute(
                text("select connection_broken_at from payment_gateway_configs")
            )
        ).all()
        avisos = (
            await conn.execute(
                text(
                    "select count(*) from outbox_messages where event_type = "
                    "'store.mercadopago_connection_broken'"
                )
            )
        ).scalar_one()
        turnos = (
            await conn.execute(text("select count(*) from appointments"))
        ).scalar_one()
    assert len(marcas) == 1 and marcas[0][0] is not None, marcas
    assert avisos == 1
    assert turnos == 0

    # Con la conexion rota y sin WhatsApp, la siguiente rebota sin escribir.
    siguiente = await reservar(CUANTAS)
    assert siguiente.status_code == 409, siguiente.text
    assert siguiente.json()["error_code"] == "DEPOSIT_CHANNEL_UNAVAILABLE"
