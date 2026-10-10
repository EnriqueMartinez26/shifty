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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from core.database import TenantSession, set_tenant_context
import modules.notifications.tasks as tasks
import modules.payments.jobs as payment_jobs
import modules.payments.service as payments_service
import modules.payments.tasks as payment_tasks
from modules.payments.jobs import expire_unpaid_appointments
from tests.integration.test_mails_al_cliente import Buzon
from tests.postgres.conftest import APP_URL, OWNER_URL, _sync_dsn
from tests.postgres.test_pg_lotes_skip_locked import (
    CUANTOS,
    _reservas_con_sena_pendiente,
    _tienda_con_mercadopago,
)

pytestmark = pytest.mark.postgres

DEMORA_MP = 0.3


async def _expirar_con_bypass_sin_transaccion_inicial(
    sessions: async_sessionmaker[AsyncSession],
) -> dict[str, int]:
    """Configura bypass, pero deja que el job tome el lock antes de abrir DB."""
    async with sessions() as db:
        set_tenant_context(None, True)
        try:
            return await expire_unpaid_appointments(db)
        finally:
            set_tenant_context(None, False)


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
                                # Solo esta base: el cluster es compartido y
                                # otra suite en otra base no cuenta.
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
        _expirar_con_bypass_sin_transaccion_inicial(app_sessions),
        _expirar_con_bypass_sin_transaccion_inicial(app_sessions),
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


def _ociosas_en_transaccion_de_la_app() -> int:
    """Conexiones de ``shifty_app`` en ESTA base que estan idle in transaction.

    psycopg2 y no el ``owner_engine``: se llama desde el hilo de la tarea de
    Celery, con otro event loop.
    """
    assert OWNER_URL
    conn = psycopg2.connect(_sync_dsn(OWNER_URL))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from pg_stat_activity "
                "where usename = 'shifty_app' "
                "and datname = current_database() "
                "and state = 'idle in transaction'"
            )
            fila = cur.fetchone()
            assert fila is not None
            return int(fila[0])
    finally:
        conn.close()


def _tarea_del_beat() -> dict[str, int]:
    """La tarea REAL del beat (``payments/tasks.py``), en su propio hilo y loop.

    ``run_in_worker_loop`` no se anida dentro del loop del test: el test la
    reemplaza por ``asyncio.run`` y corre la tarea con ``asyncio.to_thread``.
    """
    return dict(payment_tasks.expire_unpaid_appointment_holds(limit=100))


@pytest.mark.asyncio
async def test_la_corrida_que_pierde_el_lock_no_queda_idle_in_transaction(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#142/#143, 2026-10-09: la tarea del beat abria la transaccion de la app
    (``_apply_tenant_context``) ANTES de pedir el advisory lock. La corrida que
    lo perdia quedaba ``idle in transaction`` mientras la ganadora esperaba a
    Mercado Pago. La prueba de arriba no lo veia: llama al job sin pasar por
    la tarea, que era donde se abria la transaccion.

    Aca las dos corridas son la tarea de Celery real. La ganadora esta adentro
    del HTTP lento a MP cuando arranca la perdedora; ``pg_stat_activity`` se
    mira en el instante en que la perdedora sabe que perdio (todavia dentro de
    su sesion): tiene que haber CERO conexiones de la app idle in transaction.
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    assert APP_URL
    # Engine propio de las tareas: cada una corre en su hilo con su loop, y
    # con NullPool ninguna conexion queda atada a un loop ya cerrado.
    engine_tareas = create_async_engine(APP_URL, poolclass=NullPool)
    monkeypatch.setattr(
        payment_tasks,
        "AsyncSessionFactory",
        async_sessionmaker(
            class_=TenantSession,
            bind=engine_tareas,
            expire_on_commit=False,
            autoflush=False,
        ),
    )
    monkeypatch.setattr(payment_tasks, "run_in_worker_loop", asyncio.run)
    durante_mp: list[int] = []
    perdedora: list[dict[str, int]] = []
    # Solo el HTTP del job: las preferencias de las reservas no cuentan.
    expirando: list[bool] = []

    exclusive_job_real = payment_jobs._exclusive_job

    @asynccontextmanager
    async def exclusive_job_espiado(db: AsyncSession, name: str) -> AsyncIterator[bool]:
        async with exclusive_job_real(db, name) as tomado:
            if not tomado:
                # La perdedora, antes de salir de su sesion.
                durante_mp.append(_ociosas_en_transaccion_de_la_app())
            yield tomado

    monkeypatch.setattr(payment_jobs, "_exclusive_job", exclusive_job_espiado)

    async def mercadopago_lento(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return {
                "id": "pref-143-pg",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=143",
            }
        if expirando and not perdedora:
            # Primer HTTP de la ganadora: el beat dispara otra corrida
            # mientras esta espera a MP.
            perdedora.append(await asyncio.to_thread(_tarea_del_beat))
        await asyncio.sleep(DEMORA_MP)
        if path.startswith("/v1/payments/search"):
            return {"results": []}
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mercadopago_lento)
    store, token = await _tienda_con_mercadopago(client, app_sessions, "s143-tarea")
    await _reservas_con_sena_pendiente(client, token, store, "s143-tarea")
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("update appointments set expires_at = :vencido"),
            {"vencido": datetime.now(timezone.utc) - timedelta(minutes=5)},
        )

    expirando.append(True)
    try:
        ganadora = await asyncio.to_thread(_tarea_del_beat)
    finally:
        await engine_tareas.dispose()

    # Antes de #143: [1] (la sesion de la tarea perdedora, con su
    # set_config abierto, idle in transaction mientras la ganadora estaba en MP).
    assert durante_mp == [0], durante_mp
    # La tarea perdedora no vencio nada; la ganadora, todo el lote.
    assert perdedora == [{"expired": 0, "rescued": 0, "held": 0, "inspected": 0}]
    assert int(ganadora["expired"]) == CUANTOS, ganadora


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

    resultado = await _expirar_con_bypass_sin_transaccion_inicial(app_sessions)

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
