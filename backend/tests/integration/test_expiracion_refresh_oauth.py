"""Refresh OAuth durante la fase HTTP de la expiracion de senas (revision de S-02).

2026-09-18, rechazo de la primera version de S-02: al cerrar la transaccion
de lectura antes del HTTP, el refresh OAuth ante un 401 hacia
``await db.flush()`` en una transaccion NUEVA: sin contexto de tienda (en
Postgres, RLS dejaba el UPDATE de ``payment_gateway_configs`` en 0 filas ->
StaleDataError -> sesion inactiva -> la corrida moria para todas las
tiendas, y los tokens nuevos de MP se perdian) y, en cualquier motor, con esa
transaccion abierta durante el resto del HTTP.

Ahora el refresh del job se persiste en una transaccion corta propia, con el
contexto de la tarea, y se cierra antes de la siguiente llamada a MP.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.config import settings
from core.crypto import decrypt_secret, encrypt_secret
from modules.appointments.model import Appointment
from modules.payments.jobs import expire_unpaid_appointments
from modules.payments.model import PaymentGatewayConfig
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import _enable_payments

TOKEN_VIEJO_A = "TEST-TOKEN-OAUTH-A-VIEJO-1"
TOKEN_NUEVO_A = "TEST-TOKEN-OAUTH-A-NUEVO-2"
TOKEN_B = "TEST-TOKEN-MANUAL-B-123456"


async def _tienda_con_turno_vencido(
    client: AsyncClient, slug: str, access_token: str
) -> str:
    """Tienda con MP configurado y un turno con sena pendiente. Devuelve store_id."""
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    await _enable_payments(client, token)
    config = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={
            "access_token": access_token,
            "public_key": "TEST-PUBLIC-KEY",
            "webhook_secret": "secret-demo",
        },
    )
    assert config.status_code == 200, config.text
    service = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, service, email=f"pro-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=10, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente MP",
            "client_phone": f"+549115558{len(slug):04d}",
            "payment_method": "mercadopago",
            "accepts_terms": True,
            "idempotency_key": f"{slug}-reserva",
        },
    )
    assert reserva.status_code == 201, reserva.text
    me = await client.get("/me", headers=auth_headers(token))
    return cast(str, me.json()["store_id"])


@pytest.mark.asyncio
async def test_un_401_oauth_en_la_fase_http_refresca_persiste_y_sigue(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    linea: list[str] = []
    llamadas: list[tuple[str, str]] = []

    async def mercadopago(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return {
                "id": "pref-oauth",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=o",
            }
        linea.append("http")
        llamadas.append((access_token, path))
        if access_token == TOKEN_VIEJO_A:
            raise payments_service.MercadoPagoAPIError("token vencido", status_code=401)
        return {"results": []}

    async def token_oauth(form_data: dict[str, str]) -> dict[str, Any]:
        assert form_data["grant_type"] == "refresh_token"
        linea.append("http")
        return {"access_token": TOKEN_NUEVO_A, "refresh_token": "REFRESH-A-2"}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mercadopago)
    monkeypatch.setattr(
        payments_service, "_mercadopago_oauth_token_request", token_oauth
    )
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        settings, "MERCADOPAGO_OAUTH_REDIRECT_URI", "https://api.test/callback"
    )

    tienda_a = await _tienda_con_turno_vencido(client, "oauth-a", TOKEN_VIEJO_A)
    tienda_b = await _tienda_con_turno_vencido(client, "manual-b", TOKEN_B)
    await test_session.execute(
        update(PaymentGatewayConfig)
        .where(PaymentGatewayConfig.store_id == tienda_a)
        .values(
            connection_mode="oauth",
            encrypted_refresh_token=encrypt_secret("REFRESH-A-1"),
        )
    )
    await test_session.execute(
        update(Appointment).values(
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5)
        )
    )
    await test_session.commit()
    linea.clear()
    llamadas.clear()

    def sql(*args: Any, **kwargs: Any) -> None:
        linea.append("sql")

    def commit(*args: Any, **kwargs: Any) -> None:
        linea.append("commit")

    event.listen(test_engine.sync_engine, "before_cursor_execute", sql)
    event.listen(test_engine.sync_engine, "commit", commit)
    try:
        stats = await expire_unpaid_appointments(test_session)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", sql)
        event.remove(test_engine.sync_engine, "commit", commit)

    # La corrida termino bien para las dos tiendas.
    assert stats["expired"] == 2, stats
    tokens_usados = [token for token, _ in llamadas]
    # Tienda A: 401 con el token viejo, reintento con el nuevo.
    assert tokens_usados.count(TOKEN_VIEJO_A) == 1, llamadas
    assert tokens_usados.count(TOKEN_NUEVO_A) == 1, llamadas
    # Tienda B: no se entero.
    assert tokens_usados.count(TOKEN_B) == 1, llamadas

    # Ninguna llamada externa corrio con una transaccion abierta: antes de
    # cada "http", lo ultimo que paso en la base fue un commit.
    for i, evento in enumerate(linea):
        if evento == "http":
            previos = [e for e in linea[:i] if e in ("sql", "commit")]
            assert previos and previos[-1] == "commit", linea

    # El token nuevo quedo persistido.
    test_session.expire_all()
    config_a = (
        await test_session.execute(
            select(PaymentGatewayConfig).where(
                PaymentGatewayConfig.store_id == tienda_a
            )
        )
    ).scalar_one()
    assert decrypt_secret(config_a.encrypted_access_token) == TOKEN_NUEVO_A
    assert decrypt_secret(config_a.encrypted_refresh_token or "") == "REFRESH-A-2"

    # Y la config de la otra tienda quedo intacta.
    config_b = (
        await test_session.execute(
            select(PaymentGatewayConfig).where(
                PaymentGatewayConfig.store_id == tienda_b
            )
        )
    ).scalar_one()
    assert decrypt_secret(config_b.encrypted_access_token) == TOKEN_B
    assert config_b.connection_mode != "oauth"
