"""Dos corridas del outbox no vencen dos veces el mismo link de Mercado Pago.

Audit B1-04 (2026-09-18). ``release_pending`` ya no llama a MP: publica
``payment.preference.expire`` y ``process_outbox_batch`` lo vence en dos
fases (reclamo bajo ``FOR UPDATE SKIP LOCKED`` + commit, llamada sin lock ni
transaccion, resultado en una transaccion nueva). Entre el commit del reclamo
y el resultado no hay lock: lo que evita que otra corrida lo tome es el
reclamo (``processed_at`` provisorio + marcador). En SQLite no hay
concurrencia real; esto solo se prueba contra Postgres.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import modules.payments.service as payments_service
from core.database import tenant_bypass
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import OutboxMessage
from modules.payments.service import EVENT_PREFERENCE_EXPIRE
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_dos_corridas_del_outbox_vencen_el_link_una_sola_vez(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vencimientos: list[str] = []

    async def mp_lento(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert access_token
        if method == "POST":
            return {
                "id": "pref-pg-b104",
                "sandbox_init_point": "https://sandbox.mercadopago.com/x?pref=pg",
            }
        # Lento a proposito: la segunda corrida arma su lote mientras la
        # primera todavia esta hablando con MP.
        await asyncio.sleep(0.5)
        vencimientos.append(path)
        return {"id": "pref-pg-b104", "expires": True}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp_lento)

    store, token = await register_and_login(
        client, app_sessions, slug="pg-vence-link", email="pg-vence-link@demo.com"
    )
    politica = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"deposit_policy": "La sena se descuenta del total."},
    )
    assert politica.status_code == 200, politica.text
    flags = await client.put(
        "/stores/me/feature-flags", headers=auth_headers(token), json={"payments": True}
    )
    assert flags.status_code == 200, flags.text
    gateway = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={"access_token": "TEST-PG-B104-TOKEN"},
    )
    assert gateway.status_code == 200, gateway.text
    service = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="fixed",
        deposit_amount=2500,
    )
    staff = await create_staff(client, token, service, email="pro-pg-b104@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=3)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=12, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Pg Release",
            "client_phone": "+5491155557001",
            "payment_method": "mercadopago",
            "idempotency_key": "pg-vence-link-reserva-0001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    liberado = await client.patch(
        f"/appointments/{reserva.json()['public_id']}/release",
        headers=auth_headers(token),
    )
    assert liberado.status_code == 200, liberado.text
    assert vencimientos == [], "liberar no puede llamar a MP"

    async def corrida() -> dict[str, int]:
        async with app_sessions() as db:
            async with tenant_bypass(db):
                return await process_outbox_batch(db)

    await asyncio.gather(corrida(), corrida())

    assert vencimientos == ["/checkout/preferences/pref-pg-b104"], vencimientos
    async with app_sessions() as db:
        async with tenant_bypass(db):
            evento = (
                await db.execute(
                    select(OutboxMessage).where(
                        OutboxMessage.event_type == EVENT_PREFERENCE_EXPIRE
                    )
                )
            ).scalar_one()
            assert evento.processed_at is not None
            assert evento.error is None


@pytest.mark.asyncio
async def test_el_lote_principal_del_outbox_usa_el_indice_parcial(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """El filtro ``event_type != 'payment.preference.expire'`` (B1-04) es un
    predicado extra sobre las filas de ``ix_outbox_pending``: el planner lo
    sigue usando. Con ``enable_seqscan = off`` el plan solo puede ser otro si
    el WHERE ya no implica ``processed_at IS NULL``."""
    from sqlalchemy import text

    import modules.payments.jobs as jobs

    capturado: list[Any] = []

    async with app_sessions() as db:
        async with tenant_bypass(db):
            original = db.execute

            async def espiar(statement: Any, *args: Any, **kwargs: Any) -> Any:
                if "event_type !=" in str(statement) and not capturado:
                    capturado.append(statement)
                return await original(statement, *args, **kwargs)

            db.execute = espiar  # type: ignore[method-assign]
            await jobs.process_outbox_batch(db)
            db.execute = original  # type: ignore[method-assign]

            assert capturado, "no se ejecuto el lote principal"
            sql = capturado[0].compile(
                dialect=db.get_bind().dialect, compile_kwargs={"literal_binds": True}
            )
            await db.execute(text("SET LOCAL enable_seqscan = off"))
            plan = (await db.execute(text(f"EXPLAIN {sql}"))).scalars().all()
            await db.rollback()
    assert any("ix_outbox_pending" in linea for linea in plan), plan
