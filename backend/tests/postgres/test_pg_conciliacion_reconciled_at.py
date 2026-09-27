"""La cola de la conciliacion y su marca ``reconciled_at``, contra Postgres real.

Revision de 3b977a9..6c84d46 (#4) y de 6c84d46..79a64e4 (#1):

- La conciliacion ordena por ``reconciled_at NULLS FIRST, created_at``: con
  ``limit`` la corrida siguiente consulta la cola, no otra vez el frente.
- La marca es un UPDATE por lote sin el lock del turno (excepcion a la regla
  7): toma las filas en orden de id con ``FOR UPDATE SKIP LOCKED``. Un pago
  que otra transaccion tiene tomado (un webhook a mitad de camino) se
  saltea en esta corrida, sin esperar el ``lock_timeout`` y sin que la marca
  de los demas falle.
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.payments.jobs as jobs
from core.config import settings
from modules.payments.model import Payment
from tests.integration.test_mails_al_cliente import Buzon
from tests.postgres.test_pg_lotes_skip_locked import (
    _con_bypass,
    _mercadopago_lento,
    _reservas_con_sena_pendiente,
    _tienda_con_mercadopago,
)

pytestmark = pytest.mark.postgres


async def _cobros_en_orden(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    slug: str,
) -> list[str]:
    monkeypatch.setattr(settings, "RECONCILIATION_MIN_AGE_MINUTES", 0)
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago_lento(monkeypatch, [])
    store, token = await _tienda_con_mercadopago(client, sessions, slug)
    await _reservas_con_sena_pendiente(client, token, store, slug)
    async with owner_engine.begin() as conn:
        ids = [
            str(fila[0])
            for fila in (
                await conn.execute(text("select id from payments order by id"))
            ).all()
        ]
        base = datetime.now(timezone.utc) - timedelta(hours=1)
        for n, cobro_id in enumerate(ids):
            await conn.execute(
                text("update payments set created_at = :c where id = :id"),
                {"c": base + timedelta(minutes=n), "id": cobro_id},
            )
    return ids


def _mp_sin_novedades(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    consultados: list[str] = []

    async def mp(_db: Any, payment: Payment, *_args: Any, **_kwargs: Any) -> None:
        consultados.append(payment.id)
        return None

    monkeypatch.setattr(jobs, "_fetch_remote_payment", mp)
    return consultados


async def _marcas(owner_engine: AsyncEngine) -> dict[str, Any]:
    async with owner_engine.connect() as conn:
        filas = await conn.execute(text("select id, reconciled_at from payments"))
        return {str(i): marca for i, marca in filas.all()}


@pytest.mark.asyncio
async def test_la_corrida_siguiente_consulta_la_cola(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cobros = await _cobros_en_orden(
        client, app_sessions, owner_engine, monkeypatch, "cola-pg"
    )
    consultados = _mp_sin_novedades(monkeypatch)

    async def corrida(db: AsyncSession) -> dict[str, int]:
        return await jobs.reconcile_pending_payments(db, limit=2)

    await _con_bypass(app_sessions, corrida)
    primera = list(consultados)
    consultados.clear()
    await _con_bypass(app_sessions, corrida)

    assert primera == cobros[:2], primera
    assert consultados[0] == cobros[2], consultados
    assert all(m is not None for m in (await _marcas(owner_engine)).values())


@pytest.mark.asyncio
async def test_la_marca_saltea_un_pago_tomado_sin_esperar(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cobros = await _cobros_en_orden(
        client, app_sessions, owner_engine, monkeypatch, "marca-tomada-pg"
    )
    _mp_sin_novedades(monkeypatch)
    tomado = cobros[1]

    async with owner_engine.connect() as otro:
        transaccion = await otro.begin()
        # Otro escritor (un webhook) tiene el pago tomado.
        await otro.execute(
            text("select id from payments where id = :id for update"),
            {"id": tomado},
        )
        inicio = time.monotonic()
        resultado = await asyncio.wait_for(
            _con_bypass(app_sessions, jobs.reconcile_pending_payments), timeout=30
        )
        transcurrido = time.monotonic() - inicio
        await transaccion.rollback()

    assert resultado["inspected"] == 3, resultado
    # Sin SKIP LOCKED la marca esperaba el lock_timeout del rol y fallaba
    # entera: ningun cobro quedaba marcado.
    assert transcurrido < 3, transcurrido
    marcas = await _marcas(owner_engine)
    assert marcas[tomado] is None, marcas
    assert all(marcas[c] is not None for c in cobros if c != tomado), marcas
