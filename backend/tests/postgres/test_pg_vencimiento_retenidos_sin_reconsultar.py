"""Un retenido por integridad no se reconsulta cada minuto, contra Postgres.

Seguimiento W2 de la PR #104 (2026-10-03). Cambia la consulta del job de
retenciones vencidas (``_expired_holds_query``): un cobro con
``payments.integrity_held_at`` de la ultima hora no entra, y el sello se
escribe en un savepoint con el turno bloqueado (``FOR UPDATE SKIP LOCKED`` de
la fase B), como rol ``shifty_app`` bajo RLS (CLAUDE.md §4).

La tienda A tiene sus tres retenciones pagadas "de prueba" y la tienda B tres
sin pagar; con una sola pagina por corrida (``EXPIRE_MAX_PAGES = 1``) y
``limit = 3``, antes las de A ocupaban todas las corridas y las de B no
vencian nunca. Ahora la primera corrida estaciona las de A, la segunda vence
las de B sin preguntarle a MP por las de A, y pasada la hora las de A vuelven
a la consulta. ``oldest_overdue_hold_at`` no cuenta las estacionadas.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.payments.jobs as jobs
import modules.payments.processing as processing
import modules.payments.service as payments_service
from core.config import Environment, settings
from modules.payments.jobs import expire_unpaid_appointments, oldest_overdue_hold_at
from modules.payments.model import external_reference_for
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import _stub_mercadopago
from tests.postgres.test_pg_lotes_skip_locked import (
    CUANTOS,
    _con_bypass,
    _reservas_con_sena_pendiente,
    _tienda_con_mercadopago,
)
from tests.postgres.test_pg_vencimiento_con_cobro_rechazado import (
    _cobros_de,
    _estados,
)

pytestmark = pytest.mark.postgres

CUENTA = "COLLECTOR-PG-W2"


async def _remotos_de_prueba(
    owner_engine: AsyncEngine, store: str
) -> dict[str, dict[str, Any]]:
    remotos: dict[str, dict[str, Any]] = {}
    for cobro in await _cobros_de(owner_engine, store):
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
    return remotos


async def _sellados(owner_engine: AsyncEngine, store: str) -> int:
    async with owner_engine.connect() as conn:
        return int(
            (
                await conn.execute(
                    text(
                        "select count(*) from payments p "
                        "join stores s on s.id = p.store_id "
                        "where (s.public_id = :store or s.id = :store) "
                        "and p.integrity_held_at is not null"
                    ),
                    {"store": store},
                )
            ).scalar_one()
        )


@pytest.mark.asyncio
async def test_los_retenidos_se_estacionan_y_las_retenciones_nuevas_vencen(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    store_a, token_a = await _tienda_con_mercadopago(client, app_sessions, "pg-w2-a")
    await _reservas_con_sena_pendiente(client, token_a, store_a, "pg-w2-a")
    store_b, token_b = await _tienda_con_mercadopago(client, app_sessions, "pg-w2-b")
    await _reservas_con_sena_pendiente(client, token_b, store_b, "pg-w2-b")
    remotos = await _remotos_de_prueba(owner_engine, store_a)
    assert len(remotos) == CUANTOS
    consultas: list[str] = []

    async def mercadopago(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        consultas.append(path)
        for turno, remoto in remotos.items():
            if turno in path:
                return {"results": [remoto]}
        return {"results": []}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mercadopago)
    monkeypatch.setattr(processing, "report_exception", lambda exc, **c: None)
    monkeypatch.setattr(jobs, "report_exception", lambda exc, **c: None)
    monkeypatch.setattr(jobs, "EXPIRE_MAX_PAGES", 1)
    ahora = datetime.now(timezone.utc)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("update payment_gateway_configs set oauth_user_id = :cuenta"),
            {"cuenta": CUENTA},
        )
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

    def de_a() -> int:
        return sum(any(t in path for t in remotos) for path in consultas)

    primera = await _con_bypass(app_sessions, vencer)
    consultas_a = de_a()

    async def mas_vieja(db: AsyncSession) -> Any:
        return {"t": await oldest_overdue_hold_at(db, ahora, store_id=None)}

    # Las de A estacionadas no cuentan: la mas vieja es una de B (hace 5 min).
    vieja: Any = (await _con_bypass(app_sessions, mas_vieja))["t"]
    segunda = await _con_bypass(app_sessions, vencer)

    assert (primera["held"], primera["expired"]) == (CUANTOS, 0), primera
    assert await _sellados(owner_engine, store_a) == CUANTOS
    assert vieja is not None and vieja > ahora - timedelta(minutes=10), vieja
    assert (segunda["held"], segunda["expired"]) == (0, CUANTOS), segunda
    assert de_a() == consultas_a, "la segunda corrida le volvio a preguntar a MP"
    assert await _estados(owner_engine, store_b) == [("expired", "expired")] * CUANTOS
    assert (
        await _estados(owner_engine, store_a)
        == [("pending_payment", "pending")] * CUANTOS
    )
    sin_atraso: Any = (await _con_bypass(app_sessions, mas_vieja))["t"]
    assert sin_atraso is None

    # Pasada la hora, las de A vuelven a la consulta.
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "update payments set integrity_held_at = :t "
                "where integrity_held_at is not null"
            ),
            {"t": ahora - jobs.EXPIRE_HELD_RECHECK_INTERVAL - timedelta(minutes=1)},
        )
    tercera = await _con_bypass(app_sessions, vencer)

    assert tercera["held"] == CUANTOS, tercera
    assert de_a() > consultas_a
