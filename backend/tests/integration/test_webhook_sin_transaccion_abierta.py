"""El webhook HTTP cierra la transaccion antes de consultar a Mercado Pago.

2026-09-20, AUD2-B2-08: el handler abria transaccion con las consultas de
``_validate_mercadopago_signature`` y recien despues hacia
``enrich_mercadopago_webhook_payload``, que es un ``GET /v1/payments/{id}`` de
hasta ``MP_REQUEST_TIMEOUT`` (mas un refresh OAuth si da 401). La sesion
quedaba ``idle in transaction`` todo ese rato, que es justo lo que S-02
arreglo en el job de vencimiento y AUD2-B2-02 en los dos lotes del beat. Con
``idle_in_transaction_session_timeout = 60s`` (migracion ``app_role_timeouts``)
y Mercado Pago degradado, Postgres podia matar la conexion: el webhook salia
500 hacia MP y la fila del inbox se perdia con el rollback, que es el sintoma
que B2-04 vino a cerrar por el otro lado.

En SQLite se observa el ORDEN con eventos del engine, igual que en
``test_lotes_sin_transaccion_abierta``: antes de la llamada a MP hay un
commit, y entre ese commit y la ultima llamada a MP no se ejecuta ninguna
sentencia SQL.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from modules.payments.model import Payment, PaymentStatus, WebhookInbox
from tests.integration.test_expiracion_sin_transaccion_abierta import (
    _sql_entre_el_commit_y_el_ultimo_http,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
    webhook_signature_headers,
)
from tests.integration.test_lotes_sin_transaccion_abierta import (
    _dejar_de_escuchar,
    _escuchar,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _book_with_mercadopago,
    _configure_gateway,
    _enable_payments,
)


def _mercadopago_que_registra(
    monkeypatch: pytest.MonkeyPatch, linea: list[str], remoto: dict[str, Any]
) -> None:
    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return {
                "id": "pref-b208",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=b208",
            }
        linea.append("http")
        return remoto

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


@pytest.mark.asyncio
async def test_el_webhook_consulta_a_mp_sin_transaccion_abierta(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    linea: list[str] = []
    _mercadopago_que_registra(monkeypatch, linea, {})
    store, token = await register_and_login(
        client, slug="b208-webhook", email="b208-webhook@t.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix="b208-webhook", hour=10
    )
    cobro = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == turno)
        )
    ).scalar_one()
    _mercadopago_que_registra(
        monkeypatch,
        linea,
        {
            "id": "pago-b208",
            "status": "approved",
            "external_reference": turno,
            "preference_id": cobro.preference_id,
            "transaction_amount": float(cobro.amount),
            "currency_id": cobro.currency,
        },
    )
    linea.clear()

    sql, commit = _escuchar(test_engine, linea)
    try:
        respuesta = await client.post(
            f"/payments/webhooks/mercadopago?store_id={store}",
            json={"id": "evt-b208", "type": "payment", "data": {"id": "pago-b208"}},
            headers=webhook_signature_headers(
                secret="secret-demo",
                data_id="pago-b208",
                request_id="req-b208",
                ts="1710000000",
            ),
        )
    finally:
        _dejar_de_escuchar(test_engine, sql, commit)

    assert respuesta.status_code == 200, respuesta.text
    assert "http" in linea, linea
    assert _sql_entre_el_commit_y_el_ultimo_http(linea) == [], (
        f"la transaccion del request seguia abierta durante el GET a MP: {linea}"
    )


@pytest.mark.asyncio
async def test_el_webhook_sigue_aplicando_el_pago_y_sellando_el_inbox(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guarda: cerrar la transaccion antes del HTTP no cambia el contrato.

    El handler sigue resolviendo el cobro en el request (``applied: true``),
    sigue sellando la fila del inbox y sigue siendo idempotente por
    ``event_id`` (regla 7).
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    linea: list[str] = []
    _mercadopago_que_registra(monkeypatch, linea, {})
    store, token = await register_and_login(
        client, slug="b208-contrato", email="b208-contrato@t.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix="b208-contrato", hour=11
    )
    cobro = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == turno)
        )
    ).scalar_one()
    _mercadopago_que_registra(
        monkeypatch,
        linea,
        {
            "id": "pago-b208-c",
            "status": "approved",
            "external_reference": turno,
            "preference_id": cobro.preference_id,
            "transaction_amount": float(cobro.amount),
            "currency_id": cobro.currency,
        },
    )

    async def entregar() -> Any:
        return await client.post(
            f"/payments/webhooks/mercadopago?store_id={store}",
            json={"id": "evt-b208-c", "type": "payment", "data": {"id": "pago-b208-c"}},
            headers=webhook_signature_headers(
                secret="secret-demo",
                data_id="pago-b208-c",
                request_id="req-b208-c",
                ts="1710000000",
            ),
        )

    primera = await entregar()
    assert primera.status_code == 200, primera.text
    cuerpo = primera.json()
    assert cuerpo.get("data", cuerpo) == {"received": True, "applied": True}

    await test_session.refresh(cobro)
    assert cobro.status == PaymentStatus.APPROVED.value
    inbox = (
        await test_session.execute(
            select(WebhookInbox).where(
                WebhookInbox.event_id == "mercadopago:evt-b208-c"
            )
        )
    ).scalar_one()
    assert inbox.processed_at is not None and inbox.error is None

    # Reentrega del mismo evento: corta temprano, no vuelve a aplicar nada.
    repetida = await entregar()
    assert repetida.status_code == 200, repetida.text
    repetido = repetida.json()
    assert repetido.get("data", repetido) == {"status": "already_processed"}
