"""Un cobro que no pasa la integridad no frena el vencimiento, contra Postgres.

Revision 4R de la PR #104 (2026-10-02, CRITICO). En produccion, un aprobado
de MP con ``live_mode = false`` (el smoke test con un vendedor de prueba)
levantaba ``RuntimeError`` dentro de la fase B del job de retenciones
vencidas, revertia el lote entero y, como era el turno mas viejo, encabezaba
cada corrida: el vencimiento se frenaba para todas las tiendas.

Contra Postgres real (CLAUDE.md §4: job por lotes con ``FOR UPDATE SKIP
LOCKED``, RLS y savepoints): la tienda A tiene sus tres retenciones pagadas
"de prueba" y ocupa toda la primera pagina (``limit = 3``); la tienda B tiene
tres sin pagar. Una corrida retiene las de A (ni rescatadas ni liberadas),
pide la pagina siguiente sin ellas y vence las de B. La segunda corrida no
vuelve a avisar a Sentry: la marca de la alerta quedo commiteada aunque el
savepoint del cobro se revirtio.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.payments.processing as processing
import modules.payments.service as payments_service
from core.config import Environment, settings
from modules.payments.jobs import expire_unpaid_appointments
from modules.payments.model import external_reference_for
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import _stub_mercadopago
from tests.postgres.test_pg_lotes_skip_locked import (
    CUANTOS,
    _con_bypass,
    _reservas_con_sena_pendiente,
    _tienda_con_mercadopago,
)

pytestmark = pytest.mark.postgres

CUENTA = "COLLECTOR-PG"


async def _cobros_de(owner_engine: AsyncEngine, store: str) -> list[dict[str, Any]]:
    async with owner_engine.connect() as conn:
        filas = await conn.execute(
            text(
                "select p.appointment_id, p.link_ref, p.amount, p.currency "
                "from payments p join stores s on s.id = p.store_id "
                "where s.public_id = :store or s.id = :store"
            ),
            {"store": store},
        )
        return [dict(f._mapping) for f in filas.all()]


async def _estados(owner_engine: AsyncEngine, store: str) -> list[tuple[str, str]]:
    async with owner_engine.connect() as conn:
        filas = await conn.execute(
            text(
                "select a.status, p.status from appointments a "
                "join payments p on p.appointment_id = a.id "
                "join stores s on s.id = a.store_id "
                "where s.public_id = :store or s.id = :store"
            ),
            {"store": store},
        )
        return sorted((str(a), str(p)) for a, p in filas.all())


@pytest.mark.asyncio
async def test_los_cobros_de_prueba_quedan_retenidos_y_el_resto_vence(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    # MP simulado desde las reservas: crear el link de pago tambien llama a MP
    # (la primera corrida de CI salio a la red real y la reserva dio 502).
    _stub_mercadopago(monkeypatch, remote_payment=None)
    store_a, token_a = await _tienda_con_mercadopago(client, app_sessions, "pg-ret-a")
    await _reservas_con_sena_pendiente(client, token_a, store_a, "pg-ret-a")
    store_b, token_b = await _tienda_con_mercadopago(client, app_sessions, "pg-ret-b")
    await _reservas_con_sena_pendiente(client, token_b, store_b, "pg-ret-b")

    remotos: dict[str, dict[str, Any]] = {}
    for cobro in await _cobros_de(owner_engine, store_a):
        turno = str(cobro["appointment_id"])
        remotos[turno] = {
            "id": f"mp-{turno}",
            "status": "approved",
            "external_reference": external_reference_for(turno, cobro["link_ref"]),
            "transaction_amount": float(cobro["amount"]),
            "currency_id": cobro["currency"],
            "collector_id": CUENTA,
            "live_mode": False,
        }
    assert len(remotos) == CUANTOS

    async def mercadopago(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for turno, remoto in remotos.items():
            if turno in path:
                return {"results": [remoto]}
        return {"results": []}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mercadopago)
    avisos: list[dict[str, Any]] = []
    monkeypatch.setattr(
        processing,
        "report_exception",
        lambda exc, **contexto: avisos.append(contexto),
    )

    ahora = datetime.now(timezone.utc)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("update payment_gateway_configs set oauth_user_id = :cuenta"),
            {"cuenta": CUENTA},
        )
        # Las de A son las mas viejas: encabezan la cola de vencimiento.
        for turno in remotos:
            await conn.execute(
                text("update appointments set expires_at = :t where id = :id"),
                {"t": ahora - timedelta(hours=2), "id": turno},
            )
        await conn.execute(
            text(
                "update appointments set expires_at = :t "
                "where expires_at > :t and status = 'pending_payment'"
            ),
            {"t": ahora - timedelta(minutes=5)},
        )
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)

    async def vencer(db: AsyncSession) -> dict[str, int]:
        return await expire_unpaid_appointments(db, limit=CUANTOS)

    primera = await _con_bypass(app_sessions, vencer)
    segunda = await _con_bypass(app_sessions, vencer)

    assert (primera["held"], primera["expired"]) == (CUANTOS, CUANTOS), primera
    assert (segunda["held"], segunda["expired"]) == (CUANTOS, 0), segunda
    assert (
        await _estados(owner_engine, store_a)
        == [("pending_payment", "pending")] * CUANTOS
    )
    assert await _estados(owner_engine, store_b) == [("expired", "expired")] * CUANTOS
    # Una alerta por pago de MP, no una por corrida.
    assert sorted(a["mp_payment_id"] for a in avisos) == sorted(
        r["id"] for r in remotos.values()
    ), avisos
    async with owner_engine.connect() as conn:
        marcas = (
            await conn.execute(
                text(
                    "select count(*) from outbox_messages "
                    "where event_type = 'payment.integrity_alert' "
                    "and processed_at is not null"
                )
            )
        ).scalar_one()
    assert marcas == CUANTOS
