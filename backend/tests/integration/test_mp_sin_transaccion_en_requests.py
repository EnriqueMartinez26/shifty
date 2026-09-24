"""Los requests que hablan con Mercado Pago no lo hacen con la transaccion abierta.

2026-09-24, F1-05 (R8-05): el patron de AUD2-B2-08 (commit plano de
``AsyncSession`` -> llamada externa -> ``_apply_tenant_context``) ya lo tenian
el webhook y los jobs, pero no:

- el link de la reserva publica (``PublicBookingService._attach_payment_link``),
- el link de pago del panel (``create_panel_payment_preference``, fase 2),
- el callback y el refresh de OAuth.

En los cuatro, las lecturas previas a la red (cobro, config del gateway,
tienda, pagador) abrian una transaccion que quedaba ``idle in transaction``
durante el HTTP (hasta 20 s por llamada) con el pool de 15 conexiones. El
``commit`` de ``TenantSession`` no alcanza: reaplica el contexto y con eso
reabre otra transaccion en el acto.

En SQLite se observa el ORDEN con eventos del engine, como en
``test_webhook_sin_transaccion_abierta``: entre el ultimo commit anterior a
la primera llamada a MP y la ultima llamada no se ejecuta ninguna sentencia.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.config import settings
from core.crypto import decrypt_secret
from modules.payments.model import Payment, PaymentGatewayConfig
from modules.stores.model import Store
from tests.integration.test_cobro_del_panel_dos_fases import _turno_con_cobro_online
from tests.integration.test_expiracion_sin_transaccion_abierta import (
    _sql_entre_el_commit_y_el_ultimo_http,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
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


def _preferencia_que_registra(
    monkeypatch: pytest.MonkeyPatch, linea: list[str]
) -> None:
    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        linea.append("http")
        return {
            "id": f"pref-f105-{len(linea)}",
            "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=f105",
        }

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


def _oauth_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_ID", "client-f105")
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_SECRET", "secret-f105")
    monkeypatch.setattr(
        settings,
        "MERCADOPAGO_OAUTH_REDIRECT_URI",
        "https://api.shifty.test/payments/mercadopago/oauth/callback",
    )


def _token_oauth_que_registra(
    monkeypatch: pytest.MonkeyPatch, linea: list[str], access_token: str
) -> None:
    async def fake_token(form_data: dict[str, str]) -> dict[str, Any]:
        linea.append("http")
        return {
            "access_token": access_token,
            "refresh_token": f"refresh-{access_token}",
            "public_key": "APP_USR-f105",
            "user_id": "105",
            "scope": "offline_access",
        }

    monkeypatch.setattr(payments_service, "_mercadopago_oauth_token_request", fake_token)


async def _con_escucha(
    engine: AsyncEngine, linea: list[str], pedido: Any
) -> Any:
    linea.clear()
    sql, commit = _escuchar(engine, linea)
    try:
        return await pedido()
    finally:
        _dejar_de_escuchar(engine, sql, commit)


@pytest.mark.asyncio
async def test_la_reserva_publica_pide_el_link_sin_transaccion_abierta(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    linea: list[str] = []
    _preferencia_que_registra(monkeypatch, linea)
    store, token = await register_and_login(
        client, slug="f105-reserva", email="f105-reserva@t.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)

    async def reservar() -> str:
        return await _book_with_mercadopago(
            client, token, store, slug_suffix="f105-reserva", hour=10
        )

    # La escucha cubre tambien el alta del servicio y del profesional: lo que
    # importa es el tramo entre el ultimo commit y la llamada a MP.
    turno = await _con_escucha(test_engine, linea, reservar)

    assert linea.count("http") == 1, linea
    assert _sql_entre_el_commit_y_el_ultimo_http(linea) == [], (
        f"la reserva hablaba con MP con la transaccion abierta: {linea}"
    )
    cobro = (
        await test_session.execute(select(Payment).where(Payment.appointment_id == turno))
    ).scalar_one()
    await test_session.refresh(cobro)
    assert cobro.preference_id.startswith("pref-f105-")


@pytest.mark.asyncio
async def test_el_link_del_panel_se_pide_sin_transaccion_abierta(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    linea: list[str] = []
    _preferencia_que_registra(monkeypatch, linea)
    _store, token = await register_and_login(
        client, slug="f105-panel", email="f105-panel@t.com"
    )
    _servicio, turno = await _turno_con_cobro_online(client, token, "f105-panel")

    async def pedir_link() -> Any:
        return await client.post(
            f"/payments/preferences/{turno}", headers=auth_headers(token)
        )

    respuesta = await _con_escucha(test_engine, linea, pedir_link)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["payment_link"].startswith("https://www.mercadopago.com/")
    assert linea.count("http") == 1, linea
    assert _sql_entre_el_commit_y_el_ultimo_http(linea) == [], (
        f"el panel hablaba con MP con la transaccion abierta: {linea}"
    )


async def _conectar_por_oauth(
    client: AsyncClient, token: str, test_engine: AsyncEngine, linea: list[str]
) -> Any:
    await _enable_payments(client, token)
    start = await client.post(
        "/payments/mercadopago/oauth/start", headers=auth_headers(token)
    )
    assert start.status_code == 200, start.text
    state = start.json()["auth_url"].split("state=")[1].split("&", 1)[0]

    async def callback() -> Any:
        return await client.get(
            f"/payments/mercadopago/oauth/callback?code=code-f105&state={state}"
        )

    return await _con_escucha(test_engine, linea, callback)


@pytest.mark.asyncio
async def test_el_callback_de_oauth_canjea_el_codigo_sin_transaccion_abierta(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _oauth_configurado(monkeypatch)
    linea: list[str] = []
    _token_oauth_que_registra(monkeypatch, linea, "APP_USR-callback")
    _store, token = await register_and_login(
        client, slug="f105-oauth", email="f105-oauth@t.com"
    )

    respuesta = await _conectar_por_oauth(client, token, test_engine, linea)

    assert respuesta.status_code == 303, respuesta.text
    assert "mercadopago=connected" in respuesta.headers["location"]
    assert linea.count("http") == 1, linea
    assert _sql_entre_el_commit_y_el_ultimo_http(linea) == [], (
        f"el callback canjeaba el codigo con la transaccion abierta: {linea}"
    )
    config = (
        await test_session.execute(select(PaymentGatewayConfig))
    ).scalar_one()
    await test_session.refresh(config)
    assert decrypt_secret(config.encrypted_access_token) == "APP_USR-callback"


@pytest.mark.asyncio
async def test_el_refresh_de_oauth_llama_a_mp_sin_transaccion_abierta(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _oauth_configurado(monkeypatch)
    linea: list[str] = []
    _token_oauth_que_registra(monkeypatch, linea, "APP_USR-viejo")
    store_public_id, token = await register_and_login(
        client, slug="f105-refresh", email="f105-refresh@t.com"
    )
    conectado = await _conectar_por_oauth(client, token, test_engine, linea)
    assert conectado.status_code == 303, conectado.text
    _token_oauth_que_registra(monkeypatch, linea, "APP_USR-nuevo")

    async def refrescar() -> Any:
        return await client.post(
            "/payments/mercadopago/oauth/refresh", headers=auth_headers(token)
        )

    respuesta = await _con_escucha(test_engine, linea, refrescar)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["connection_mode"] == "oauth"
    assert linea.count("http") == 1, linea
    assert _sql_entre_el_commit_y_el_ultimo_http(linea) == [], (
        f"el refresh llamaba a MP con la transaccion abierta: {linea}"
    )
    store = (
        await test_session.execute(select(Store).where(Store.public_id == store_public_id))
    ).scalar_one()
    config = (
        await test_session.execute(
            select(PaymentGatewayConfig).where(PaymentGatewayConfig.store_id == store.id)
        )
    ).scalar_one()
    await test_session.refresh(config)
    assert decrypt_secret(config.encrypted_access_token) == "APP_USR-nuevo"
