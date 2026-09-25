"""La compensacion de un link de MP fallido borra de verdad bajo RLS.

2026-09-24, revision de F1-04/F1-05. El link de Mercado Pago ahora se pide
despues de un commit PLANO de ``AsyncSession``, que no reaplica el contexto
de tenant; el contexto vuelve con ``_apply_tenant_context`` en un ``finally``.
Si esa reaplicacion faltara, los ``DELETE`` de la compensacion correrian en
una transaccion sin ``store_id`` y la RLS los dejaria en 0 filas sin error:
el turno quedaria retenido y el cobro huerfano. SQLite no tiene RLS; esto se
prueba contra Postgres con el rol de la app y se cuenta con el rol dueno.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.circuit_breaker import AsyncCircuitBreaker
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres


async def _mercadopago_caido(*args: Any, **kwargs: Any) -> dict[str, Any]:
    raise payments_service.MercadoPagoAPIError(
        "Mercado Pago devolvio HTTP 500", status_code=500, transient=True
    )


async def _contar(owner_engine: AsyncEngine, tabla: str) -> int:
    async with owner_engine.connect() as conn:
        return int(
            (await conn.execute(text(f"select count(*) from {tabla}"))).scalar_one()
        )


async def _tienda(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, app_sessions, slug=slug, email=f"{slug}@demo.com"
    )
    headers = auth_headers(token)
    for metodo, ruta, cuerpo in (
        ("PATCH", "/stores/me", {"deposit_policy": "La sena se descuenta del total."}),
        ("PUT", "/stores/me/feature-flags", {"payments": True}),
        (
            "PUT",
            "/payments/gateway-config",
            {
                "access_token": "TEST-ACCESS-TOKEN-1234567890",
                "public_key": "TEST-PUBLIC-KEY",
                "webhook_secret": "secret-demo",
            },
        ),
    ):
        res = await client.request(metodo, ruta, headers=headers, json=cuerpo)
        assert res.status_code == 200, res.text
    servicio = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return store, token, servicio, staff, dia


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    monkeypatch.setattr(
        payments_service, "_mercadopago_api_request", _mercadopago_caido
    )
    # Breaker propio: las fallas de este test no abren el del proceso.
    monkeypatch.setattr(
        payments_service,
        "_mercadopago_breaker",
        AsyncCircuitBreaker(
            name="mercadopago-test", failure_threshold=50, recovery_timeout_seconds=30
        ),
    )


@pytest.mark.asyncio
async def test_la_reserva_publica_compensada_no_deja_turno_ni_cobro(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, _token, servicio, staff, dia = await _tienda(
        client, app_sessions, "pg-comp-publica"
    )

    res = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=10, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Compensado",
            "client_phone": "+5491155578001",
            "payment_method": "mercadopago",
            "accepts_terms": True,
        },
    )

    assert res.status_code == 502, res.text
    assert res.json()["error_code"] == "PAYMENT_LINK_CREATION_FAILED"
    assert await _contar(owner_engine, "appointments") == 0
    assert await _contar(owner_engine, "payments") == 0


@pytest.mark.asyncio
async def test_el_link_del_panel_compensado_borra_el_cobro_que_creo(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """El panel corre con el contexto de la tienda (sin bypass): es el caso
    donde un DELETE sin contexto quedaria en 0 filas."""
    _store, token, servicio, staff, dia = await _tienda(
        client, app_sessions, "pg-comp-panel"
    )
    turno = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": "pg-comp-panel-turno",
        },
    )
    assert turno.status_code == 201, turno.text

    res = await client.post(
        f"/payments/preferences/{turno.json()['public_id']}",
        headers=auth_headers(token),
    )

    assert res.status_code == 502, res.text
    assert await _contar(owner_engine, "payments") == 0
    # El turno del panel no es parte de la compensacion: sigue en pie.
    assert await _contar(owner_engine, "appointments") == 1
