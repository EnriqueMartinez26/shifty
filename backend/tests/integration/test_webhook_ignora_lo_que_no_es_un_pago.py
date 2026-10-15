"""El webhook de Mercado Pago responde 200 a lo que no es un pago, sin tocar nada.

2026-10-14, produccion: nginx registro 8 POST a ``/payments/webhooks/mercadopago``
por UN pago real. Uno respondio 200 y se aplico bien; los otros 7, 400. MP no
manda solo el webhook firmado de ``payment``: al ``notification_url`` de la
preferencia tambien llegan las notificaciones IPN/feed (``?topic=...&id=...``,
cuerpo ``{"resource": ..., "topic": ...}``, sin ``x-signature``), las de
``merchant_order`` y webhooks de otros tipos (``topic_merchant_order_wh``).
Todas caian en ``WebhookException`` (400): "Headers de firma faltantes" o "No
se pudo resolver data.id". Un no-2xx repetido hace que MP reintente y puede
marcar o apagar el endpoint.

Lo que se fija aca:

- una notificacion que se declara de OTRO tema (ningun ``topic``/``type`` es
  ``payment``) responde 200 ``ignored`` sin consultar a MP, sin escribir en el
  inbox y sin tocar la base: nada de lo que hace el webhook lee esos eventos
  (la consulta es siempre ``GET /v1/payments/{id}``);
- una notificacion de PAGO sin firma sigue rechazada (regla 7): el webhook
  firmado es el unico camino que aplica un pago, y la conciliacion recoge lo
  que se pierda. Basta con que UN indicador diga ``payment`` (o que no haya
  ninguno) para que se exija la firma: clasificar mal hacia "ignorar" perderia
  un pago, clasificar mal hacia "validar" solo responde 400 como antes.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import modules.payments.service as payments_service
from modules.payments.model import WebhookInbox
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
    webhook_signature_headers,
)
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
)

URL = "/payments/webhooks/mercadopago"


def _mp_que_registra(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    llamadas: list[str] = []

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        llamadas.append(path)
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)
    return llamadas


async def _tienda(client: AsyncClient, slug: str) -> str:
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@test.com")
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    return store


async def _filas_del_inbox(session: AsyncSession) -> int:
    session.expire_all()
    return int(
        (
            await session.execute(select(func.count()).select_from(WebhookInbox))
        ).scalar_one()
    )


def _ignorada(respuesta: Any) -> None:
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    datos = cuerpo.get("data", cuerpo)
    assert datos == {"received": True, "ignored": True}


# Las formas en que MP manda lo que NO es un pago, tal como llegan.
NO_PAGOS: dict[str, tuple[dict[str, str], Any, bool]] = {
    # IPN/feed de la orden: query ``topic``/``id``, cuerpo con ``resource``.
    "feed_merchant_order": (
        {"topic": "merchant_order", "id": "31234567890"},
        {
            "resource": "https://api.mercadolibre.com/merchant_orders/31234567890",
            "topic": "merchant_order",
        },
        False,
    ),
    # Webhook firmado de la orden (``topic_merchant_order_wh``).
    "webhook_merchant_order_firmado": (
        {"data.id": "31234567890", "type": "topic_merchant_order_wh"},
        {
            "id": "31234567890",
            "type": "topic_merchant_order_wh",
            "action": "update",
            "data": {"id": "31234567890"},
        },
        True,
    ),
    # El mismo IPN de la orden, con el cuerpo vacio o roto: el tema esta en la query.
    "feed_merchant_order_sin_cuerpo": (
        {"topic": "merchant_order", "id": "31234567890"},
        None,
        False,
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("forma", sorted(NO_PAGOS))
async def test_lo_que_no_es_un_pago_responde_200_sin_guardar_nada(
    forma: str,
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llamadas = _mp_que_registra(monkeypatch)
    store = await _tienda(client, f"ignora-{forma.replace('_', '-')}")
    query, cuerpo, firmado = NO_PAGOS[forma]
    headers = (
        webhook_signature_headers(
            secret="secret-demo", data_id=query["data.id"], request_id="req-mo", ts="0"
        )
        if firmado
        else {}
    )
    kwargs: dict[str, Any] = (
        {"json": cuerpo}
        if cuerpo is not None
        else {"content": b"", "headers": {"content-type": "application/json"}}
    )
    if headers:
        kwargs.setdefault("headers", {}).update(headers)

    respuesta = await client.post(URL, params={"store_id": store, **query}, **kwargs)

    _ignorada(respuesta)
    assert await _filas_del_inbox(test_session) == 0
    assert llamadas == [], "un evento que no es un pago no se consulta en MP"


@pytest.mark.asyncio
async def test_lo_ignorado_no_toca_la_base_ni_con_una_tienda_inexistente(
    client: AsyncClient, test_engine: AsyncEngine
) -> None:
    consultas: list[str] = []

    def anotar(
        conn: Any, cursor: Any, statement: str, *args: Any, **kwargs: Any
    ) -> None:
        consultas.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", anotar)
    try:
        respuesta = await client.post(
            URL,
            params={
                "store_id": "01J0000000000000000000NADA",
                "topic": "merchant_order",
                "id": "1",
            },
            json={"resource": "1", "topic": "merchant_order"},
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", anotar)

    _ignorada(respuesta)
    assert not [c for c in consultas if "webhook_inbox" in c or "stores" in c]


# Las notificaciones de PAGO sin firma siguen rechazadas, como hoy.
PAGOS_SIN_FIRMA: dict[str, tuple[dict[str, str], dict[str, Any]]] = {
    "ipn_payment": (
        {"topic": "payment", "id": "1234567890"},
        {"resource": "1234567890", "topic": "payment"},
    ),
    "webhook_payment_sin_firma": (
        {"data.id": "1234567890", "type": "payment"},
        {"id": "evt-1", "type": "payment", "data": {"id": "1234567890"}},
    ),
    # Un indicador dice pago y otro no: manda el que exige la firma.
    "temas_mezclados": (
        {"topic": "merchant_order", "id": "1234567890"},
        {"id": "evt-2", "type": "payment", "data": {"id": "1234567890"}},
    ),
    # Sin ningun indicador de tema se trata como hasta ahora.
    "sin_tema": (
        {"data.id": "1234567890"},
        {"id": "evt-3", "data": {"id": "1234567890"}},
    ),
    # El tema lo puede declarar la accion aunque falte el tipo.
    "accion_de_pago": (
        {"data.id": "1234567890", "type": "merchant_order"},
        {"id": "evt-4", "action": "payment.updated", "data": {"id": "1234567890"}},
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("forma", sorted(PAGOS_SIN_FIRMA))
async def test_un_pago_sin_firma_sigue_rechazado(
    forma: str,
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llamadas = _mp_que_registra(monkeypatch)
    store = await _tienda(client, f"rechaza-{forma.replace('_', '-')}")
    query, cuerpo = PAGOS_SIN_FIRMA[forma]

    respuesta = await client.post(URL, params={"store_id": store, **query}, json=cuerpo)

    assert respuesta.status_code == 400, respuesta.text
    assert "ignored" not in respuesta.text
    assert await _filas_del_inbox(test_session) == 0
    assert llamadas == []


@pytest.mark.asyncio
async def test_un_pago_con_firma_invalida_sigue_401(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llamadas = _mp_que_registra(monkeypatch)
    store = await _tienda(client, "rechaza-firma-mala")
    headers = webhook_signature_headers(
        secret="otro-secreto", data_id="1234567890", request_id="req-x", ts="0"
    )

    respuesta = await client.post(
        URL,
        params={"store_id": store, "data.id": "1234567890", "type": "payment"},
        json={"id": "evt-5", "type": "payment", "data": {"id": "1234567890"}},
        headers=headers,
    )

    assert respuesta.status_code == 401, respuesta.text
    assert await _filas_del_inbox(test_session) == 0
    assert llamadas == []
