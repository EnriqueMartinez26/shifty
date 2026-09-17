"""El outbox manda los mails DESPUES del commit, contra Postgres real (B2-01).

2026-09-16, hallazgo B2-01: el lote mandaba los avisos al dueno por SMTP
dentro de la transaccion que sostiene el ``FOR UPDATE SKIP LOCKED``. En SQLite
no hay segunda conexion que pueda mirar si la fila esta commiteada; aca si:
en el momento en que sale cada mail, OTRA conexion (rol dueno) ya tiene que
ver ``processed_at`` persistido para ESA fila. Ademas, dos workers solapados
no mandan dos veces el mismo aviso (SKIP LOCKED) ni pierden ninguno.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.payments.jobs as payments_jobs
from core.database import _apply_tenant_context, set_tenant_context
from modules.payments.jobs import process_outbox_batch
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.postgres.conftest import register_and_login

pytestmark = pytest.mark.postgres

CUANTOS = 4


async def _tienda_con_reservas_manuales(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    store, token = await register_and_login(
        client, sessions, slug="outbox-mails", email="outbox-mails@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email="pro-outbox@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    base = dia.replace(hour=12, minute=0, second=0, microsecond=0)
    for i in range(CUANTOS):
        reserva = await client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": service,
                "staff_id": staff,
                "starts_at": (base + timedelta(hours=i)).isoformat(),
                "client_name": f"Cliente {i}",
                "client_phone": f"+54911555{i:05d}",
                "payment_method": "manual",
                "accepts_terms": True,
                "idempotency_key": f"outbox-mails-pg-{i:06d}",
            },
        )
        assert reserva.status_code == 201, reserva.text


async def _commiteado_segun_otra_conexion(
    owner_engine: AsyncEngine, client_name: str
) -> bool:
    """Si la BASE ya tiene processed_at para el aviso de ese cliente.

    Es otra conexion: solo ve lo commiteado. Si el mail saliera dentro de la
    transaccion del lote, aca la fila se veria todavia pendiente.
    """
    async with owner_engine.connect() as conn:
        marca = (
            await conn.execute(
                text(
                    "select processed_at from outbox_messages "
                    "where event_type = 'appointment.pending_confirmation' "
                    "and payload->>'client_name' = :name"
                ),
                {"name": client_name},
            )
        ).scalar_one()
        return marca is not None


async def _pendientes_segun_otra_conexion(owner_engine: AsyncEngine) -> int:
    async with owner_engine.connect() as conn:
        total = (
            await conn.execute(
                text(
                    "select count(*) from outbox_messages "
                    "where event_type = 'appointment.pending_confirmation' "
                    "and processed_at is null"
                )
            )
        ).scalar_one()
        return cast(int, total)


@pytest.mark.asyncio
async def test_el_aviso_al_dueno_sale_con_la_fila_ya_commiteada_y_una_sola_vez(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    await _tienda_con_reservas_manuales(client, app_sessions)

    commiteado_al_enviar: list[bool] = []
    enviados: list[str] = []

    async def dueno(
        *, email: str, title: str, body: str | None = None
    ) -> dict[str, str]:
        # El cuerpo arranca con "Cliente N reservo ...": identifica la fila.
        nombre = (body or "").split(" reservo", 1)[0]
        commiteado_al_enviar.append(
            await _commiteado_segun_otra_conexion(owner_engine, nombre)
        )
        # Un SMTP lento: si el lote todavia tuviera el FOR UPDATE, el otro
        # worker quedaria afuera y este envio pasaria con la fila sin commit.
        await asyncio.sleep(0.05)
        enviados.append(body or "")
        return {"status": "sent"}

    monkeypatch.setattr(payments_jobs, "send_store_notification_email", dueno)

    async def worker() -> dict[str, int]:
        async with app_sessions() as db:
            set_tenant_context(None, True)
            try:
                await _apply_tenant_context(db)
                return await process_outbox_batch(db)
            finally:
                set_tenant_context(None, False)

    resultados = await asyncio.gather(worker(), worker())

    assert sum(int(r["processed"]) for r in resultados) == CUANTOS
    assert all(int(r["failed"]) == 0 for r in resultados), resultados
    # Cada aviso salio una sola vez (SKIP LOCKED) y ninguno se perdio.
    assert sorted(enviados) == sorted(
        f"Cliente {i} reservo Consulta y va a coordinar el pago. "
        "Confirmalo cuando recibas la transferencia."
        for i in range(CUANTOS)
    )
    # Y en el momento de cada envio SU fila ya estaba commiteada: el commit
    # fue antes del mail (regla 5 / CLAUDE.md Fases 4-7).
    assert commiteado_al_enviar == [True] * CUANTOS, commiteado_al_enviar
    assert await _pendientes_segun_otra_conexion(owner_engine) == 0
