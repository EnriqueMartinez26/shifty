"""El resumen de conciliacion se arma con un GROUP BY, no con 11 consultas.

2026-09-17, hallazgo B2-07: ``GET /payments/reconciliation/summary`` hacia 5
``COUNT`` (uno por estado), 3 ``SUM`` (uno por estado) y 3 conteos sobre inbox
y outbox: 11 idas y vueltas secuenciales a Postgres por cada carga del panel.
Los ocho primeros son un unico ``GROUP BY status`` sobre ``payments``.

Fija dos cosas: (a) el contrato de ``ReconciliationSummaryResponse`` no cambia,
incluido el 0 explicito de un estado sin filas (que un GROUP BY no devuelve) y
el filtro ``store_id`` (los pagos de otra tienda no cuentan); (b) sobre
``payments``, ``webhook_inbox`` y ``outbox_messages`` viaja una sola sentencia
por tabla (3 en lugar de 11), y la de ``payments`` agrupa por estado.
"""

from decimal import Decimal
import re
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from modules.payments.model import (
    OutboxMessage,
    Payment,
    PaymentStatus,
    WebhookInbox,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
    seed_store_and_admin,
)

# (estado, importe) de la tienda bajo prueba. No hay ninguno `refunded` ni
# `expired` a proposito: el resumen tiene que devolver 0, no omitirlos.
PAGOS_PROPIOS: list[tuple[str, str]] = [
    (PaymentStatus.PENDING.value, "100.00"),
    (PaymentStatus.PENDING.value, "50.50"),
    (PaymentStatus.APPROVED.value, "300.00"),
    (PaymentStatus.MANUAL_CONFIRMED.value, "200.00"),
    (PaymentStatus.REJECTED.value, "10.00"),
]
# Misma forma, otra tienda: si se filtran mal, inflan cada conteo y cada suma.
PAGOS_AJENOS: list[tuple[str, str]] = [
    (PaymentStatus.PENDING.value, "999.00"),
    (PaymentStatus.APPROVED.value, "999.00"),
    (PaymentStatus.REFUNDED.value, "999.00"),
]


def _pago(store_id: str, indice: int, estado: str, importe: str) -> Payment:
    return Payment(
        store_id=store_id,
        appointment_id=f"turno-{store_id}-{indice}",
        amount=Decimal(importe),
        status=estado,
    )


async def _sembrar(test_session: AsyncSession, *, propia: str, ajena: str) -> None:
    for indice, (estado, importe) in enumerate(PAGOS_PROPIOS):
        test_session.add(_pago(propia, indice, estado, importe))
    for indice, (estado, importe) in enumerate(PAGOS_AJENOS):
        test_session.add(_pago(ajena, indice, estado, importe))
    test_session.add_all(
        [
            WebhookInbox(store_id=propia, event_id="wh-pendiente", payload={}),
            WebhookInbox(
                store_id=propia,
                event_id="wh-fallido",
                payload={},
                error="payload corrupto",
            ),
            WebhookInbox(store_id=ajena, event_id="wh-ajeno", payload={}),
            OutboxMessage(store_id=propia, event_type="noop", payload={}),
            OutboxMessage(store_id=ajena, event_type="noop", payload={}),
        ]
    )
    await test_session.commit()


@pytest.mark.asyncio
async def test_el_resumen_de_conciliacion_agrupa_por_estado_en_una_consulta(
    client: AsyncClient, test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    _, token = await register_and_login(
        client, slug="b207-concilia", email="b207@test.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags", headers=auth_headers(token), json={"payments": True}
    )
    assert flags.status_code == 200, flags.text
    me = await client.get("/me", headers=auth_headers(token))
    assert me.status_code == 200, me.text
    propia = me.json()["store_id"]
    # seed_store_and_admin fija public_id = id, asi que sirve como store_id.
    ajena = await seed_store_and_admin(slug="b207-ajena", email="b207-ajena@test.com")
    await _sembrar(test_session, propia=propia, ajena=ajena)

    sentencias: list[str] = []

    def _capturar(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        sentencias.append(" ".join(statement.lower().split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", _capturar)
    try:
        resumen = await client.get(
            "/payments/reconciliation/summary", headers=auth_headers(token)
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _capturar)
    assert resumen.status_code == 200, resumen.text
    cuerpo = resumen.json()

    # Contrato: mismos campos, mismos valores, solo la tienda propia, y 0
    # explicito para el estado sin filas.
    assert cuerpo["pending_payments"] == 2
    assert cuerpo["approved_payments"] == 1
    assert cuerpo["rejected_payments"] == 1
    assert cuerpo["manual_confirmed_payments"] == 1
    assert cuerpo["refunded_payments"] == 0
    assert Decimal(cuerpo["total_pending_amount"]) == Decimal("150.50")
    assert Decimal(cuerpo["total_approved_amount"]) == Decimal("500.00")
    assert cuerpo["pending_webhooks"] == 1
    assert cuerpo["failed_webhooks"] == 1
    assert cuerpo["pending_outbox"] == 1

    # Regla 11/12: una sentencia por tabla, y la de pagos agrupa por estado.
    sobre_pagos = [s for s in sentencias if re.search(r"\bfrom payments\b", s)]
    sobre_inbox = [s for s in sentencias if re.search(r"\bfrom webhook_inbox\b", s)]
    sobre_outbox = [s for s in sentencias if re.search(r"\bfrom outbox_messages\b", s)]
    assert len(sobre_pagos) == 1, f"{len(sobre_pagos)} consultas sobre payments"
    assert "group by" in sobre_pagos[0], sobre_pagos[0]
    assert "store_id" in sobre_pagos[0], sobre_pagos[0]
    assert len(sobre_inbox) == 1, f"{len(sobre_inbox)} consultas sobre webhook_inbox"
    assert len(sobre_outbox) == 1, (
        f"{len(sobre_outbox)} consultas sobre outbox_messages"
    )
