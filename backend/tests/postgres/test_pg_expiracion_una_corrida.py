"""Expiracion de senas: una corrida a la vez y sin transaccion abierta durante MP.

2026-09-18, S-02 (seguimiento de B2-02). Contra Postgres real:

- Dos corridas simultaneas del beat no le preguntan dos veces a Mercado Pago
  por el mismo cobro. La fase A lee sin lock, asi que antes las dos corridas
  hacian el HTTP por cada cobro; ahora un advisory lock de sesion por tarea
  (``pg_try_advisory_lock`` en ``_exclusive_job``) deja pasar una y la otra
  sale sin hacer nada.
- Mientras se habla con MP ninguna conexion de la app queda
  ``idle in transaction``: con ``idle_in_transaction_session_timeout = 60s``
  en el rol, Postgres mataba la conexion a mitad del job con MP degradado.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from modules.payments.jobs import expire_unpaid_appointments
from tests.integration.test_mails_al_cliente import Buzon
from tests.postgres.test_pg_lotes_skip_locked import (
    CUANTOS,
    _con_bypass,
    _reservas_con_sena_pendiente,
    _tienda_con_mercadopago,
)

pytestmark = pytest.mark.postgres

DEMORA_MP = 0.3


@pytest.mark.asyncio
async def test_dos_corridas_de_expiracion_no_consultan_dos_veces_el_mismo_cobro(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    llamadas: list[str] = []
    ociosas_en_transaccion: list[int] = []

    async def mercadopago_lento(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return {
                "id": "pref-s02-pg",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=s02",
            }
        llamadas.append(path)
        async with owner_engine.connect() as conn:
            ociosas_en_transaccion.append(
                int(
                    (
                        await conn.execute(
                            text(
                                "select count(*) from pg_stat_activity "
                                "where usename = 'shifty_app' "
                                "and datname = current_database() "
                                "and state = 'idle in transaction'"
                            )
                        )
                    ).scalar_one()
                )
            )
        await asyncio.sleep(DEMORA_MP)
        if path.startswith("/v1/payments/search"):
            return {"results": []}
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mercadopago_lento)
    store, token = await _tienda_con_mercadopago(client, app_sessions, "s02-doble")
    await _reservas_con_sena_pendiente(client, token, store, "s02-doble")
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("update appointments set expires_at = :vencido"),
            {"vencido": datetime.now(timezone.utc) - timedelta(minutes=5)},
        )
    llamadas.clear()

    resultados = await asyncio.gather(
        _con_bypass(app_sessions, expire_unpaid_appointments),
        _con_bypass(app_sessions, expire_unpaid_appointments),
    )

    # Cada cobro se consulto UNA vez (antes: 2N busquedas) ...
    assert len(llamadas) == CUANTOS, llamadas
    assert len(set(llamadas)) == CUANTOS, llamadas
    # ... y todo el lote vencio una sola vez.
    assert sum(int(r["expired"]) for r in resultados) == CUANTOS, resultados
    # Durante el HTTP ninguna conexion de la app estaba idle in transaction.
    assert ociosas_en_transaccion == [0] * CUANTOS, ociosas_en_transaccion
    async with owner_engine.connect() as conn:
        vencidos = (
            await conn.execute(
                text("select count(*) from appointments where status = 'expired'")
            )
        ).scalar_one()
    assert vencidos == CUANTOS


@pytest.mark.asyncio
async def test_un_401_oauth_durante_el_http_persiste_el_token_nuevo_con_rls(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revision de S-02: con RLS real, el refresh OAuth del job escribe la fila.

    La primera version flusheaba el refresh en una transaccion nueva SIN el
    contexto de la tarea: RLS dejaba el UPDATE de payment_gateway_configs en 0
    filas (StaleDataError), la corrida moria y el token nuevo se perdia.
    """
    from core.config import settings
    from core.crypto import decrypt_secret, encrypt_secret

    monkeypatch.setattr(tasks, "_send_email", Buzon())
    token_viejo = "TEST-ACCESS-TOKEN-1234567890"  # el de _configure_gateway
    token_nuevo = "TEST-TOKEN-OAUTH-RENOVADO-99"
    usados: list[str] = []

    async def mercadopago(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return {
                "id": "pref-s02-oauth",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=o",
            }
        usados.append(access_token)
        if access_token == token_viejo:
            raise payments_service.MercadoPagoAPIError("vencido", status_code=401)
        return {"results": []}

    async def token_oauth(form_data: dict[str, str]) -> dict[str, Any]:
        return {"access_token": token_nuevo, "refresh_token": "REFRESH-PG-2"}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mercadopago)
    monkeypatch.setattr(
        payments_service, "_mercadopago_oauth_token_request", token_oauth
    )
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        settings, "MERCADOPAGO_OAUTH_REDIRECT_URI", "https://api.test/callback"
    )

    store, token = await _tienda_con_mercadopago(client, app_sessions, "s02-oauth")
    await _reservas_con_sena_pendiente(client, token, store, "s02-oauth")
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "update payment_gateway_configs set connection_mode = 'oauth', "
                "encrypted_refresh_token = :refresh"
            ),
            {"refresh": encrypt_secret("REFRESH-PG-1")},
        )
        await conn.execute(
            text("update appointments set expires_at = :vencido"),
            {"vencido": datetime.now(timezone.utc) - timedelta(minutes=5)},
        )
    usados.clear()

    resultado = await _con_bypass(app_sessions, expire_unpaid_appointments)

    # La corrida termino: todo el lote vencio.
    assert int(resultado["expired"]) == CUANTOS, resultado
    # Un 401 con el token viejo; el resto, ya con el nuevo.
    assert usados.count(token_viejo) == 1, usados
    assert usados.count(token_nuevo) == CUANTOS, usados
    async with owner_engine.connect() as conn:
        fila = (
            await conn.execute(
                text(
                    "select encrypted_access_token, encrypted_refresh_token "
                    "from payment_gateway_configs"
                )
            )
        ).one()
    assert decrypt_secret(fila[0]) == token_nuevo
    assert decrypt_secret(fila[1]) == "REFRESH-PG-2"
