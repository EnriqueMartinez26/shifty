"""F1-22 (plan de rendimiento, R3-05): el lote de recordatorios no manda mails
con una transaccion abierta.

2026-09-24. Sintoma: ``claim_reminder`` commiteaba con el ``commit`` de
``TenantSession``, que reaplica el contexto de RLS y con eso abre OTRA
transaccion en el acto. La conexion quedaba "idle in transaction" durante cada
envio SMTP del lote: ocupaba una conexion del pool sin hacer nada y, con un
SMTP lento, el ``idle_in_transaction_session_timeout`` (60 s) del rol la mataba
a mitad del lote. Mismo problema y mismo arreglo que S-02 en
``payments/jobs.py``: commit plano de ``AsyncSession`` y el contexto se
reaplica recien en la sentencia siguiente.

Aca el envio es un stub lento que, mientras "manda", mira ``pg_stat_activity``
desde la conexion del dueno.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
from tests.postgres.test_pg_recordatorios_skip_locked import (
    _sin_smtp,
    _turnos_de_manana,
)

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_ningun_envio_ocurre_con_la_conexion_idle_in_transaction(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", _sin_smtp)
    turnos, primero = await _turnos_de_manana(client, app_sessions)
    estados_durante_envios: list[list[str]] = []

    async def envio_lento(**kwargs: Any) -> dict[str, str]:
        await asyncio.sleep(0.2)
        async with owner_engine.connect() as conn:
            estados = [
                str(fila[0])
                for fila in (
                    await conn.execute(
                        text(
                            "select state from pg_stat_activity "
                            "where usename = 'shifty_app' "
                            "and datname = current_database()"
                        )
                    )
                ).all()
            ]
        estados_durante_envios.append(estados)
        return {"status": "sent", "channel": "email", "to": ""}

    monkeypatch.setattr(tasks, "notify_client_reminder", envio_lento)
    monkeypatch.setattr(tasks, "AsyncSessionFactory", app_sessions)

    # 06:00 UTC de manana: los cuatro turnos estan en la etapa de 24 horas.
    resultado = await tasks.process_due_appointment_reminders(
        now=primero.replace(hour=6)
    )

    assert resultado["published"] == len(turnos)
    assert len(estados_durante_envios) == len(turnos)
    assert all(
        "idle in transaction" not in estados for estados in estados_durante_envios
    ), estados_durante_envios
