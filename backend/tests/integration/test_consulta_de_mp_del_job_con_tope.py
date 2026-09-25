"""Cada consulta a MP de los jobs tiene un tope total, refresh OAuth incluido.

Revision de 3b977a9..6c84d46 (2026-09-25, #3). El presupuesto de la fase A
se mira ANTES de cada consulta, asi que el peor caso es el presupuesto mas
una consulta en vuelo. Pero una consulta no dura como mucho 20 s: ante un
401, ``_mercadopago_api_request_for_store`` refresca el OAuth y reintenta,
hasta 3 requests de 20 s cada una. Con 60 s de presupuesto eso llegaba a los
120 s del soft time limit de Celery.

Ahora cada consulta de la conciliacion, del job de vencimiento y del inbox
corre dentro de ``mercadopago_budget(MP_QUERY_BUDGET_SECONDS)`` (20 s): la
cadena entera (401, refresh, reintento) no pasa de ese tope.

Mercado Pago falso a nivel httpx (como ``test_mp_lento_presupuesto``): 401,
refresh que responde bien y un reintento lento. El tope del test es de
0,3 s y el reintento tarda 1 s de verdad.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.jobs as jobs
import modules.payments.service as payments_service
from core.config import settings
from core.crypto import encrypt_secret
from modules.payments.model import Payment, PaymentGatewayConfig
from tests.integration.test_expiracion_refresh_oauth import _tienda_con_turno_vencido
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_mp_lento_presupuesto import (
    _REQUEST_ORIGINAL,
    _breaker_propio,
    _es_mercadopago,
)

TOPE_DE_PRUEBA = 0.3
REINTENTO_LENTO = 1.0


def _mp_con_401_refresh_y_reintento_lento(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    pedidos: list[str] = []

    async def request(self: Any, method: str, url: Any, **kwargs: Any) -> Any:
        if not _es_mercadopago(self, url):
            return await _REQUEST_ORIGINAL(self, method, url, **kwargs)
        ruta = str(url)
        pedidos.append(ruta)
        pedido = httpx.Request(method, ruta)
        if ruta.endswith("/oauth/token"):
            return httpx.Response(
                200,
                json={"access_token": "TOKEN-NUEVO", "refresh_token": "REFRESH-2"},
                request=pedido,
            )
        if sum(1 for p in pedidos if "/v1/payments" in p) == 1:
            return httpx.Response(401, json={"message": "expired"}, request=pedido)
        await asyncio.sleep(REINTENTO_LENTO)
        return httpx.Response(200, json={"results": []}, request=pedido)

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    return pedidos


@pytest.mark.asyncio
async def test_la_consulta_de_la_conciliacion_no_pasa_el_tope_con_refresh_y_reintento(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _breaker_propio(monkeypatch)

    async def preferencia(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "id": "pref-tope",
            "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=t",
        }

    real = payments_service._mercadopago_api_request
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", preferencia)
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        settings, "MERCADOPAGO_OAUTH_REDIRECT_URI", "https://api.test/callback"
    )
    tienda = await _tienda_con_turno_vencido(client, "tope-oauth", "TOKEN-VIEJO-1")
    await test_session.execute(
        update(PaymentGatewayConfig)
        .where(PaymentGatewayConfig.store_id == tienda)
        .values(
            connection_mode="oauth",
            encrypted_refresh_token=encrypt_secret("REFRESH-1"),
        )
    )
    await test_session.commit()
    cobro_id = (
        await test_session.execute(select(Payment.id).where(Payment.store_id == tienda))
    ).scalar_one()
    # Desde aca, el cliente real de MP contra el httpx falso.
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", real)
    pedidos = _mp_con_401_refresh_y_reintento_lento(monkeypatch)
    monkeypatch.setattr(jobs, "MP_QUERY_BUDGET_SECONDS", TOPE_DE_PRUEBA)

    inicio = time.monotonic()
    resultado = await jobs.reconcile_one_payment(test_session, cobro_id)
    transcurrido = time.monotonic() - inicio

    # 401, refresh y el reintento: la cadena entera paso por el tope.
    assert any(p.endswith("/oauth/token") for p in pedidos), pedidos
    assert sum(1 for p in pedidos if "/v1/payments" in p) == 2, pedidos
    assert transcurrido < REINTENTO_LENTO, transcurrido
    # El reintento cortado es una consulta fallida, no un cuelgue.
    assert resultado["failed"] == 1, resultado
