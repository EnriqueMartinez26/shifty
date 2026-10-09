"""Rafaga: el personal cancela un turno con la sena por WhatsApp pendiente.

Variante de ``test_pg_cancelar_con_cobro_vivo.py`` para el cobro ``manual``
(revision 4R de la PR #108, R3 CRITICO). Cancelar desde el panel vence el
cobro vivo en la misma transaccion (regla 3, D2); con una sena por WhatsApp
el cobro tiene un link placeholder que no existe en Mercado Pago, asi que:

- UNA cancelacion responde 200 y las demas 409 ``APPOINTMENT_ALREADY_CANCELLED``
  (CLAUDE.md §4: 1 exito, N-1 conflictos), cero 5xx;
- turno ``cancelled`` y cobro ``expired`` (por el grafo);
- CERO ``payment.preference.expire`` y CERO llamadas a MP: no hay link que
  vencer;
- un solo cupo liberado.

Lo que SQLite no prueba: N requests a la vez con una sesion cada una, el
lock del turno (``lock_by_public_id``) y despues el del cobro (regla 7).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

CANCELACIONES = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))


def _mp_prohibido(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    llamadas: list[str] = []

    async def prohibido(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        llamadas.append(path)
        raise AssertionError(f"cancelar una sena por WhatsApp no llama a MP: {path}")

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", prohibido)
    return llamadas


async def _contar(owner_engine: AsyncEngine, turno: str) -> dict[str, Any]:
    async with owner_engine.connect() as conn:
        fila = (
            await conn.execute(
                text(
                    "select a.status, p.status, p.provider, "
                    "(select count(*) from outbox_messages "
                    " where event_type = 'payment.preference.expire' "
                    " and payload->>'appointment_id' = :id), "
                    "(select count(*) from outbox_messages "
                    " where event_type = 'appointment.slot_released' "
                    " and payload->>'appointment_id' = :id) "
                    "from appointments a join payments p on p.appointment_id = a.id "
                    "where a.id = :id"
                ),
                {"id": turno},
            )
        ).one()
    return {
        "turno": str(fila[0]),
        "cobro": str(fila[1]),
        "proveedor": str(fila[2]),
        "vencimientos": int(fila[3]),
        "liberados": int(fila[4]),
    }


@pytest.mark.asyncio
async def test_rafaga_de_cancelaciones_del_panel_de_una_sena_por_whatsapp(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    llamadas = _mp_prohibido(monkeypatch)
    slug = "pg-wa-cancela-panel"
    store, token = await register_and_login(
        client, app_sessions, slug=slug, email=f"{slug}@demo.com"
    )
    canal = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"whatsapp_number": "11 5555 0303"},
    )
    assert canal.status_code == 200, canal.text
    servicio = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente WhatsApp",
            "client_phone": "+5491155550777",
            "payment_method": "manual",
            "accepts_terms": True,
            "idempotency_key": f"{slug}-000001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    turno = str(reserva.json()["public_id"])

    respuestas = await asyncio.gather(
        *(
            client.patch(f"/appointments/{turno}/cancel", headers=auth_headers(token))
            for _ in range(CANCELACIONES)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(200) == 1, codigos
    assert all(
        r.json()["error_code"] == "APPOINTMENT_ALREADY_CANCELLED"
        for r in respuestas
        if r.status_code == 409
    ), [r.text for r in respuestas if r.status_code != 200]
    assert await _contar(owner_engine, turno) == {
        "turno": "cancelled",
        "cobro": "expired",
        "proveedor": "manual",
        "vencimientos": 0,
        "liberados": 1,
    }
    assert llamadas == []
