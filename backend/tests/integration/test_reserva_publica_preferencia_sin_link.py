"""Reserva publica: una preferencia sin link de checkout se manda a vencer.

Revision de perf/f4-pay (2026-09-25, seguimiento del #7). Mercado Pago puede
crear la preferencia y devolver una respuesta sin ``init_point`` usable. La
reserva se revierte (turno, cobro y canje borrados) y responde 502, pero la
preferencia seguia existiendo en MP sin que nadie la registrara. Ahora, igual
que la fase 2 del link del panel, se publica ``payment.preference.expire``
despues de la compensacion. Si publicarlo falla, se loguea y el cliente
recibe el mismo 502.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from structlog.testing import capture_logs

import modules.payments.service as payments_service
from modules.appointments.model import Appointment
from modules.payments.model import EVENT_PREFERENCE_EXPIRE, OutboxMessage, Payment
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _reserva(client: AsyncClient, slug: str) -> dict[str, Any]:
    tienda, token = await register_and_login(
        client, slug=slug, email=f"{slug}@test.com"
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
        json={
            "access_token": "TEST-ACCESS-TOKEN-1234567890",
            "public_key": "TEST-PUBLIC-KEY",
            "webhook_secret": "secret-demo",
        },
    )
    assert gateway.status_code == 200, gateway.text
    servicio = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="fixed",
        deposit_amount=2500,
    )
    profesional = await create_staff(client, token, servicio)
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, profesional, target_date=dia)
    return {
        "store_public_id": tienda,
        "service_id": servicio,
        "staff_id": profesional,
        "starts_at": dia.replace(
            hour=12, minute=30, second=0, microsecond=0
        ).isoformat(),
        "client_name": "Cliente Sin Link",
        "client_phone": "+5491122277766",
        "accepts_terms": True,
        "payment_method": "mercadopago",
        "idempotency_key": f"{slug}-0001",
    }


def _mp_sin_init_point(preferencia: str) -> Any:
    async def mp(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"id": preferencia}

    return mp


async def _vencimientos_commiteados(
    session: AsyncSession, engine: AsyncEngine
) -> list[str]:
    """Lo COMMITEADO: rollback de la sesion compartida con la app y lectura por
    otra sesion (en SQLite en memoria el engine es una sola conexion)."""
    await session.rollback()
    async with AsyncSession(engine) as otra:
        filas = await otra.execute(
            select(OutboxMessage.payload).where(
                OutboxMessage.event_type == EVENT_PREFERENCE_EXPIRE
            )
        )
        return [str(p.get("preference_id")) for p in filas.scalars()]


@pytest.mark.asyncio
async def test_la_reserva_revertida_manda_a_vencer_la_preferencia_sin_link(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reserva = await _reserva(client, "publica-sin-init")
    monkeypatch.setattr(
        payments_service, "_mercadopago_api_request", _mp_sin_init_point("pref-pub-1")
    )

    res = await client.post("/public/appointments", json=reserva)

    assert res.status_code == 502, res.text
    assert res.json()["error_code"] == "PAYMENT_LINK_CREATION_FAILED"
    assert await _vencimientos_commiteados(test_session, test_engine) == ["pref-pub-1"]
    # La compensacion de siempre: nada de la reserva queda.
    assert await test_session.scalar(select(func.count()).select_from(Appointment)) == 0
    assert await test_session.scalar(select(func.count()).select_from(Payment)) == 0


@pytest.mark.asyncio
async def test_si_vencerla_falla_la_reserva_responde_el_mismo_502(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reserva = await _reserva(client, "publica-sin-init-falla")
    monkeypatch.setattr(
        payments_service, "_mercadopago_api_request", _mp_sin_init_point("pref-pub-2")
    )

    async def outbox_caido(*_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("outbox caido")

    monkeypatch.setattr(payments_service, "_discard_unsealed_link", outbox_caido)

    with capture_logs() as logs:
        res = await client.post("/public/appointments", json=reserva)

    assert res.status_code == 502, res.text
    assert res.json()["error_code"] == "PAYMENT_LINK_CREATION_FAILED"
    fallos = [e for e in logs if e["event"] == "unsealed_preference_expire_failed"]
    assert len(fallos) == 1, logs
    assert fallos[0]["preference_id"] == "pref-pub-2"
    assert await test_session.scalar(select(func.count()).select_from(Appointment)) == 0
