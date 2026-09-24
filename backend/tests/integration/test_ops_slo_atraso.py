"""``GET /ops/slo`` mide el atraso, no solo el tamano de las colas.

F1-25 (plan de rendimiento, R9-16 y R11-16, 2026-09-24). Con los contadores
de pendientes un outbox que despacha tarde se veia igual que uno al dia, y un
mail que el presupuesto del lote dejo sin despachar no aparecia en ningun
lado. Se suman:

- ``oldest_pending_outbox_seconds`` (umbral 180 s) y
  ``oldest_pending_inbox_seconds`` (umbral 300 s): antiguedad del pendiente
  mas viejo;
- ``oldest_pending_email_send_seconds`` (umbral 180 s): desde F2-03 un mail
  que el presupuesto del despacho no alcanza queda como fila ``email.send``
  pendiente y sale en el tick siguiente. Ya no se pierde, pero se atrasa: se
  mide su antiguedad. El atraso de eventos no cuenta estas filas.

Cada tabla se resuelve con UNA sentencia agregada (regla 11) y conserva el
filtro por tienda del admin. La profundidad de la cola del broker no se
mide: pedirla desde la API es una conexion al broker por request.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from modules.payments.jobs import EVENT_EMAIL_SEND
from modules.payments.model import OutboxMessage, WebhookInbox
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


@pytest.mark.asyncio
async def test_el_slo_mide_atraso_y_mails_cortados_por_presupuesto(
    client: AsyncClient, test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="f125-slo", email="f125-slo@test.com"
    )
    tienda = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    ahora = datetime.now(timezone.utc)

    def hace(segundos: int) -> datetime:
        return ahora - timedelta(seconds=segundos)

    test_session.add_all(
        [
            # Pendientes: el mas viejo manda.
            OutboxMessage(
                store_id=tienda.id,
                event_type="x",
                payload={},
                created_at=hace(200),
            ),
            OutboxMessage(
                store_id=tienda.id, event_type="x", payload={}, created_at=hace(5)
            ),
            WebhookInbox(
                store_id=tienda.id,
                event_id="f125-a",
                payload={},
                created_at=hace(400),
            ),
            # Procesados: no son atraso.
            OutboxMessage(
                store_id=tienda.id,
                event_type="x",
                payload={},
                created_at=hace(9000),
                processed_at=hace(8000),
            ),
            WebhookInbox(
                store_id=tienda.id,
                event_id="f125-b",
                payload={},
                created_at=hace(9000),
                processed_at=hace(8000),
            ),
            # Mails diferidos por el presupuesto: el mas viejo manda, y no
            # cuentan como atraso de eventos.
            OutboxMessage(
                store_id=tienda.id,
                event_type=EVENT_EMAIL_SEND,
                payload={},
                created_at=hace(600),
            ),
            OutboxMessage(
                store_id=tienda.id,
                event_type=EVENT_EMAIL_SEND,
                payload={},
                created_at=hace(9000),
                processed_at=hace(8000),
            ),
            # Otra tienda: el admin no la ve.
            OutboxMessage(
                store_id="otra-tienda",
                event_type="x",
                payload={},
                created_at=hace(5000),
            ),
            WebhookInbox(
                store_id="otra-tienda",
                event_id="f125-c",
                payload={},
                created_at=hace(5000),
            ),
        ]
    )
    await test_session.commit()

    sentencias: list[str] = []

    def contar(
        conn: Any, cursor: Any, statement: str, *args: Any, **kwargs: Any
    ) -> None:
        if "FROM outbox_messages" in statement or "FROM webhook_inbox" in statement:
            sentencias.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", contar)
    try:
        res = await client.get("/ops/slo", headers=auth_headers(token))
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", contar)

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    metricas = cuerpo["metrics"]
    assert metricas["pending_outbox"] == 3
    assert metricas["pending_webhooks"] == 1
    assert 200 <= metricas["oldest_pending_outbox_seconds"] < 260
    assert 400 <= metricas["oldest_pending_inbox_seconds"] < 460
    assert 600 <= metricas["oldest_pending_email_send_seconds"] < 660
    assert cuerpo["thresholds"]["oldest_pending_outbox_seconds"] == 180
    assert cuerpo["thresholds"]["oldest_pending_inbox_seconds"] == 300
    assert cuerpo["thresholds"]["oldest_pending_email_send_seconds"] == 180
    assert cuerpo["status"] == "degraded"
    assert {a["code"] for a in cuerpo["alerts"]} == {
        "outbox_lag_high",
        "inbox_lag_high",
        "email_send_lag_high",
    }
    # Una sentencia agregada por tabla, con el filtro de la tienda.
    assert len(sentencias) == 2, sentencias
    assert all("store_id" in s for s in sentencias)


@pytest.mark.asyncio
async def test_sin_pendientes_el_atraso_es_cero(client: AsyncClient) -> None:
    _store, token = await register_and_login(
        client, slug="f125-vacio", email="f125-vacio@test.com"
    )

    res = await client.get("/ops/slo", headers=auth_headers(token))

    assert res.status_code == 200, res.text
    metricas = res.json()["metrics"]
    assert metricas["oldest_pending_outbox_seconds"] == 0
    assert metricas["oldest_pending_inbox_seconds"] == 0
    assert metricas["oldest_pending_email_send_seconds"] == 0
    assert res.json()["status"] == "ok"
