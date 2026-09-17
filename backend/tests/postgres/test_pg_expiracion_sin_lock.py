"""La consulta a Mercado Pago del job de expiracion corre sin el lote bloqueado,
contra Postgres real (B2-02).

2026-09-16, hallazgo B2-02: ``expire_unpaid_appointments`` tomaba los turnos
con ``FOR UPDATE SKIP LOCKED`` y recien despues le preguntaba a Mercado Pago
por cada cobro (HTTP, hasta 20 s). Aca se congela al job adentro de esa
llamada y, desde OTRA conexion, se toma ``FOR UPDATE NOWAIT`` sobre el turno:
si el lote lo tuviera bloqueado, Postgres contesta ``lock_not_available``.
Despues se suelta a MP y el turno vence igual (fase B con lock).
"""

import asyncio
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.database import _apply_tenant_context, set_tenant_context
from modules.payments.jobs import expire_unpaid_appointments
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _book_with_mercadopago,
    _configure_gateway,
    _enable_payments,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres


async def _estado_del_turno(owner_engine: AsyncEngine, appointment_id: str) -> str:
    async with owner_engine.connect() as conn:
        estado = (
            await conn.execute(
                text("select status from appointments where id = :id"),
                {"id": appointment_id},
            )
        ).scalar_one()
        return cast(str, estado)


@pytest.mark.asyncio
async def test_mientras_consulta_a_mercado_pago_el_turno_no_esta_bloqueado(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    en_mercado_pago = asyncio.Event()
    soltar = asyncio.Event()

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return {
                "id": "pref-b2-02-pg",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=pg",
            }
        # Mercado Pago degradado: la request queda colgada hasta que el test
        # termine de mirar los locks.
        en_mercado_pago.set()
        await soltar.wait()
        if path.startswith("/v1/payments/search"):
            return {"results": []}
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)

    store, token = await register_and_login(
        client, app_sessions, slug="expira-sin-lock", email="expira@demo.com"
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
    appointment_id = await _book_with_mercadopago(
        client, token, store, slug_suffix="expira-sin-lock", hour=10
    )
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "update appointments set expires_at = now() - interval '5 minutes' "
                "where id = :id"
            ),
            {"id": appointment_id},
        )

    async def worker() -> dict[str, int]:
        async with app_sessions() as db:
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(db)
                return await expire_unpaid_appointments(db)
            finally:
                set_tenant_context(None, False)

    tarea = asyncio.create_task(worker())
    try:
        await asyncio.wait_for(en_mercado_pago.wait(), timeout=15)
        # El job esta adentro de la llamada a MP. Si tuviera el lote tomado con
        # FOR UPDATE, este NOWAIT fallaria con lock_not_available (regla 5).
        async with owner_engine.connect() as conn:
            async with conn.begin():
                bloqueado = (
                    await conn.execute(
                        text(
                            "select id from appointments where id = :id "
                            "for update nowait"
                        ),
                        {"id": appointment_id},
                    )
                ).scalar_one()
                assert bloqueado == appointment_id
        # Lock ajeno liberado (fin del begin): recien ahora MP responde.
    finally:
        soltar.set()
    stats = await tarea

    assert stats["expired"] == 1 and stats["rescued"] == 0, stats
    assert await _estado_del_turno(owner_engine, appointment_id) == "expired"
