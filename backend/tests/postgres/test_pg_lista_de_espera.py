"""Lista de espera contra Postgres real: RLS de la tabla nueva y dos workers
del outbox que no duplican la oferta (SKIP LOCKED)."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
from modules.payments.jobs import process_outbox_batch
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres


async def _tienda_con_espera(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=15, minute=0, second=0, microsecond=0)
    alta = await client.post(
        "/public/waitlist",
        json={
            "store_public_id": store,
            "service_id": service,
            "window_starts_at": (slot - timedelta(hours=2)).isoformat(),
            "window_ends_at": (slot + timedelta(hours=2)).isoformat(),
            "client_name": "En Espera",
            "client_phone": f"+54911555{abs(hash(slug)) % 10000:04d}",
            "client_email": f"espera-{slug}@demo.com",
        },
    )
    assert alta.status_code == 201, alta.text
    return store, token, service, staff, slot


async def _contar_espera(
    app_engine: AsyncEngine, *, store_id: str | None, global_admin: bool = False
) -> int:
    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text(
                    "select set_config('app.current_store_id', :sid, true), "
                    "set_config('app.is_global_admin', :admin, true)"
                ),
                {"sid": store_id or "0", "admin": "true" if global_admin else "false"},
            )
            total = (
                await conn.execute(text("select count(*) from waitlist_entries"))
            ).scalar_one()
            return cast(int, total)


@pytest.mark.asyncio
async def test_rls_aisla_la_lista_de_espera_entre_tiendas(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
) -> None:
    tienda_a, token_a, *_ = await _tienda_con_espera(client, app_sessions, "espera-a")
    tienda_b, token_b, *_ = await _tienda_con_espera(client, app_sessions, "espera-b")

    assert await _contar_espera(app_engine, store_id=tienda_a) == 1
    assert await _contar_espera(app_engine, store_id=tienda_b) == 1
    assert await _contar_espera(app_engine, store_id=None) == 0
    assert await _contar_espera(app_engine, store_id=None, global_admin=True) == 2

    # Por la API cada tienda ve solo lo suyo.
    lista_a = await client.get("/waitlist/", headers=auth_headers(token_a))
    lista_b = await client.get("/waitlist/", headers=auth_headers(token_b))
    assert len(lista_a.json()) == 1 and len(lista_b.json()) == 1
    assert lista_a.json()[0]["public_id"] != lista_b.json()[0]["public_id"]


@pytest.mark.asyncio
async def test_dos_workers_del_outbox_no_duplican_la_oferta(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, token, service, staff, slot = await _tienda_con_espera(
        client, app_sessions, "espera-doble"
    )
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Titular",
            "client_phone": "+5491155559999",
            "idempotency_key": "espera-doble-000001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    cancelar = await client.patch(
        f"/appointments/{reserva.json()['public_id']}/cancel",
        headers=auth_headers(token),
    )
    assert cancelar.status_code == 200, cancelar.text

    enviados: list[tuple[str, str, str]] = []

    async def buzon(to: str, subject: str, body: str) -> bool:
        enviados.append((to, subject, body))
        return True

    monkeypatch.setattr(tasks, "_send_email", buzon)

    async def worker() -> dict[str, int]:
        from core.database import _apply_tenant_context, set_tenant_context

        async with app_sessions() as db:
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(db)
                return await process_outbox_batch(db)
            finally:
                set_tenant_context(None, False)

    resultados = await asyncio.gather(worker(), worker())
    assert sum(int(r["processed"]) for r in resultados) >= 1
    ofertas = [e for e in enviados if e[1].startswith("Se libero un turno")]
    assert len(ofertas) == 1, ofertas
