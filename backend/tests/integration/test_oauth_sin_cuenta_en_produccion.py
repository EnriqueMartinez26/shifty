"""En produccion, el callback de OAuth no guarda un token sin ``user_id``.

Revision 4R de la PR #104 (2026-10-02, R1 WARNING y R4 S3). Desde esa PR, en
produccion el webhook de Mercado Pago rechaza todo pago aprobado de una tienda
sin ``oauth_user_id``: sin la cuenta no hay contra que comparar el
``collector_id``. El callback guardaba igual un token sin ``user_id`` y
mostraba "conectada". Sintoma: la tienda cobraba y ningun pago se
acreditaba. Ahora el callback redirige con ``exchange_failed`` y no guarda
nada; fuera de produccion sigue como antes (sandbox y modo manual).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Environment, settings
from modules.payments.model import PaymentGatewayConfig
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


async def _callback_con_token_sin_cuenta(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, slug: str, *, env: str
) -> str:
    """Conecta la tienda por OAuth con un token SIN ``user_id`` y devuelve el
    ``location`` del callback."""
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@test.com")
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_ID", "client-id-demo")
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_SECRET", "secret-demo")
    monkeypatch.setattr(
        settings,
        "MERCADOPAGO_OAUTH_REDIRECT_URI",
        "https://api.shifty.test/payments/mercadopago/oauth/callback",
    )
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200, flags.text
    start = await client.post(
        "/payments/mercadopago/oauth/start", headers=auth_headers(token)
    )
    assert start.status_code == 200, start.text
    state = start.json()["auth_url"].split("state=")[1].split("&", 1)[0]

    async def fake_exchange(*, code: str, code_verifier: str) -> dict[str, str]:
        return {
            "access_token": "APP_USR-sin-cuenta",
            "refresh_token": "TG-sin-cuenta",
            "public_key": "APP_USR-public",
        }

    monkeypatch.setattr(
        "modules.payments.service.exchange_mercadopago_oauth_code", fake_exchange
    )
    monkeypatch.setattr(settings, "ENV", env)

    callback = await client.get(
        f"/payments/mercadopago/oauth/callback?code=oauth-code-demo&state={state}"
    )
    assert callback.status_code == 303, callback.text
    return callback.headers["location"]


async def _configs(session: AsyncSession) -> list[PaymentGatewayConfig]:
    session.expire_all()
    return list((await session.execute(select(PaymentGatewayConfig))).scalars().all())


@pytest.mark.asyncio
async def test_en_produccion_un_token_sin_user_id_no_queda_conectado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    location = await _callback_con_token_sin_cuenta(
        client, monkeypatch, "oauth-sin-cuenta-prod", env=Environment.PRODUCTION
    )

    assert "mercadopago=exchange_failed" in location, location
    assert await _configs(test_session) == [], "no se guarda una conexion sin cuenta"


@pytest.mark.asyncio
async def test_fuera_de_produccion_un_token_sin_user_id_se_guarda_como_antes(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    location = await _callback_con_token_sin_cuenta(
        client, monkeypatch, "oauth-sin-cuenta-dev", env=Environment.DEVELOPMENT
    )

    assert "mercadopago=connected" in location, location
    [config] = await _configs(test_session)
    assert config.connection_mode == "oauth"
    assert config.oauth_user_id is None
