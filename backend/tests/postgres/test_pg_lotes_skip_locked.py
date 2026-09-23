"""Dos corridas solapadas del inbox y de la conciliacion no toman las mismas
filas, contra Postgres real (B2-03).

2026-09-16, hallazgo B2-03: los dos lotes seleccionaban sin ``FOR UPDATE SKIP
LOCKED``. Como cada item hace HTTP a Mercado Pago, la corrida de las 10:01
alcanzaba a la de las 10:00 y repetia el ``fetch`` por evento (doble consumo
de la cuenta de la tienda) y ``attempts`` subia dos veces por el mismo
webhook. Aca dos workers corren a la vez con un MP lento: cada evento y cada
cobro se consultan UNA vez, y la suma de ``inspected`` es la cantidad de
filas, no el doble (regla 8).

2026-09-20, AUD2-B2-02: el invariante sigue igual pero lo sostiene otra
guarda. Los dos lotes pasaron a dos fases y la de Mercado Pago corre SIN lock
y con la transaccion cerrada (regla 5), asi que el ``FOR UPDATE SKIP LOCKED``
ya no cubre el HTTP: ahora la corrida entera se serializa con el advisory
lock de sesion de ``_exclusive_job``, como en ``expire_unpaid_appointments``.
La segunda corrida ya no toma un subconjunto de filas: no entra, devuelve
``inspected = 0``, y la suma sigue siendo la cantidad de filas.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.database import _apply_tenant_context, set_tenant_context
from modules.payments.jobs import (
    process_webhook_inbox_batch,
    reconcile_pending_payments,
)
from modules.payments.model import WebhookInbox
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

CUANTOS = 3
DEMORA_MP = 0.3


def _mercadopago_lento(monkeypatch: pytest.MonkeyPatch, llamadas: list[str]) -> None:
    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return {
                "id": "pref-b2-03-pg",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=pg",
            }
        llamadas.append(path)
        # Lo bastante lento para que la segunda corrida arranque con la
        # primera todavia adentro del lote.
        await asyncio.sleep(DEMORA_MP)
        if path.startswith("/v1/payments/search"):
            return {"results": []}
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


async def _tienda_con_mercadopago(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str]:
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    # Activar cobros exige la politica de sena publicada (stores/router.py,
    # DEPOSIT_POLICY_REQUIRED); la tienda de prueba nace con una, como en
    # tests/integration.
    politica = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={
            "deposit_policy": "La sena se descuenta del total y se devuelve con 24hs de aviso."
        },
    )
    assert politica.status_code == 200, politica.text
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    return store, token


async def _reservas_con_sena_pendiente(
    client: AsyncClient, token: str, store: str, slug: str
) -> None:
    """CUANTOS turnos con sena por Mercado Pago sin pagar (un solo staff)."""
    service = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    for i in range(CUANTOS):
        reserva = await client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": service,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=10 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": f"Cliente {i}",
                "client_phone": f"+54911555{i:05d}",
                "payment_method": "mercadopago",
                "accepts_terms": True,
                "idempotency_key": f"{slug}-{i:06d}",
            },
        )
        assert reserva.status_code == 201, reserva.text


async def _con_bypass(
    sessions: async_sessionmaker[AsyncSession], job: Any
) -> dict[str, int]:
    async with sessions() as db:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(db)
            return cast(dict[str, int], await job(db))
        finally:
            set_tenant_context(None, False)


@pytest.mark.asyncio
async def test_dos_corridas_del_inbox_no_toman_el_mismo_webhook(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    llamadas: list[str] = []
    _mercadopago_lento(monkeypatch, llamadas)
    store, _token = await _tienda_con_mercadopago(client, app_sessions, "inbox-doble")

    async def sembrar(db: AsyncSession) -> dict[str, int]:
        for i in range(CUANTOS):
            db.add(
                WebhookInbox(
                    store_id=store,
                    provider="mercadopago",
                    event_id=f"mercadopago:evt-{i}",
                    event_type="payment",
                    payload={
                        "id": f"evt-{i}",
                        "type": "payment",
                        "data": {"id": f"pay-{i}"},
                    },
                )
            )
        await db.commit()
        return {}

    await _con_bypass(app_sessions, sembrar)

    resultados = await asyncio.gather(
        _con_bypass(app_sessions, process_webhook_inbox_batch),
        _con_bypass(app_sessions, process_webhook_inbox_batch),
    )

    # Sin SKIP LOCKED las dos corridas inspeccionaban las mismas filas (2N).
    assert sum(int(r["inspected"]) for r in resultados) == CUANTOS, resultados
    assert sorted(llamadas) == [f"/v1/payments/pay-{i}" for i in range(CUANTOS)]
    async with owner_engine.connect() as conn:
        intentos = (
            (
                await conn.execute(
                    text("select attempts from webhook_inbox order by event_id")
                )
            )
            .scalars()
            .all()
        )
    assert list(intentos) == [1] * CUANTOS, intentos


@pytest.mark.asyncio
async def test_dos_corridas_de_conciliacion_no_consultan_dos_veces_el_mismo_cobro(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    llamadas: list[str] = []
    _mercadopago_lento(monkeypatch, llamadas)
    store, token = await _tienda_con_mercadopago(client, app_sessions, "concilia-doble")
    await _reservas_con_sena_pendiente(client, token, store, "concilia-doble")

    resultados = await asyncio.gather(
        _con_bypass(app_sessions, reconcile_pending_payments),
        _con_bypass(app_sessions, reconcile_pending_payments),
    )

    assert sum(int(r["inspected"]) for r in resultados) == CUANTOS, resultados
    busquedas = [p for p in llamadas if p.startswith("/v1/payments/search")]
    assert len(busquedas) == CUANTOS, busquedas
