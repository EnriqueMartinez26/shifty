"""El lote del inbox lee la configuracion del gateway una vez por tienda.

2026-09-17, hallazgo B2-13 (regla 12, N+1): ``process_webhook_inbox_batch``
recorria hasta 100 webhooks y, por cada uno, ``enrich_...`` volvia a leer
``payment_gateway_configs`` (via ``_mercadopago_api_request_for_store``) y
``_validate_payment_identity`` la leia otra vez: hasta 200 consultas por
corrida para, casi siempre, la misma fila de la misma tienda.

Sintoma medible: con N webhooks de una tienda, N (o 2N) SELECT sobre
``payment_gateway_configs``; ahora uno solo, armado con ``in_()`` antes del
``for`` y con ``store_id`` en el ``WHERE``.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from modules.payments.jobs import process_webhook_inbox_batch
from modules.payments.model import WebhookInbox

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
    _stub_mercadopago,
)

WEBHOOKS = 5


@pytest.mark.asyncio
async def test_el_lote_lee_la_config_del_gateway_una_vez_por_tienda(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store, token = await register_and_login(
        client, slug="inbox-n1", email="inbox-n1@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    store_id = (await client.get("/me", headers=auth_headers(token))).json()["store_id"]
    _stub_mercadopago(monkeypatch, remote_payment=None)

    for i in range(WEBHOOKS):
        test_session.add(
            WebhookInbox(
                store_id=store_id,
                provider="mercadopago",
                event_id=f"evt-n1-{i}",
                event_type="payment",
                payload={"type": "payment", "data": {"id": f"pay-n1-{i}"}},
            )
        )
    await test_session.commit()

    lecturas: list[str] = []

    def contar(
        conn: Any, cursor: Any, statement: str, *args: Any, **kwargs: Any
    ) -> None:
        if "payment_gateway_configs" in statement:
            lecturas.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", contar)
    try:
        resultado = await process_webhook_inbox_batch(test_session)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", contar)

    assert resultado["inspected"] == WEBHOOKS
    assert len(lecturas) == 1, f"{len(lecturas)} lecturas para {WEBHOOKS} webhooks"
    # Guarda de tenancy (CLAUDE.md §2): la unica lectura sigue filtrando por
    # store_id, ahora con in_() sobre las tiendas del lote.
    assert "payment_gateway_configs.store_id IN" in lecturas[0]


async def _tienda_con_token(client: AsyncClient, slug: str, access_token: str) -> str:
    _store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@test.com"
    )
    await _enable_payments(client, token)
    res = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={
            "access_token": access_token,
            "public_key": "TEST-PUBLIC-KEY",
            "webhook_secret": "secret-demo",
        },
    )
    assert res.status_code == 200, res.text
    return cast(
        str, (await client.get("/me", headers=auth_headers(token))).json()["store_id"]
    )


@pytest.mark.asyncio
async def test_con_dos_tiendas_en_el_lote_cada_webhook_usa_la_config_de_su_tienda(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El dict del lote se indexa por store_id: ningun webhook toma prestada la
    cuenta de Mercado Pago de otra tienda (y sigue siendo UNA lectura)."""
    import modules.payments.service as payments_service

    tokens = {
        await _tienda_con_token(client, "inbox-a", "TEST-TOKEN-TIENDA-A-123456"): (
            "TEST-TOKEN-TIENDA-A-123456"
        ),
        await _tienda_con_token(client, "inbox-b", "TEST-TOKEN-TIENDA-B-123456"): (
            "TEST-TOKEN-TIENDA-B-123456"
        ),
    }
    usados: dict[str, str] = {}

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        usados[path.rsplit("/", 1)[-1]] = access_token
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)

    for i, store_id in enumerate(list(tokens) * 2):
        test_session.add(
            WebhookInbox(
                store_id=store_id,
                provider="mercadopago",
                event_id=f"evt-2t-{i}",
                event_type="payment",
                payload={"type": "payment", "data": {"id": f"pay-{store_id}-{i}"}},
            )
        )
    await test_session.commit()

    lecturas: list[str] = []

    def contar(
        conn: Any, cursor: Any, statement: str, *args: Any, **kwargs: Any
    ) -> None:
        if "payment_gateway_configs" in statement:
            lecturas.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", contar)
    try:
        resultado = await process_webhook_inbox_batch(test_session)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", contar)

    assert resultado["inspected"] == 4
    assert len(lecturas) == 1
    assert len(usados) == 4
    for pago, token_usado in usados.items():
        store_id = pago.split("-")[1]
        assert token_usado == tokens[store_id], pago
