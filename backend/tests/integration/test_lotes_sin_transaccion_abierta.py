"""El inbox y la conciliacion cierran la transaccion antes de salir a MP.

2026-09-20, AUD2-B2-02: el arreglo de B2-02 (sacar el HTTP de abajo del
``FOR UPDATE``) y el de S-02 (cerrar la transaccion antes del HTTP) se
aplicaron SOLO a ``expire_unpaid_appointments`` y a
``_claim_and_expire_preferences``. Los otros dos lotes del beat seguian con
el patron viejo: tomaban el lote con ``FOR UPDATE SKIP LOCKED`` y, dentro del
mismo ``for`` y de la misma transaccion, hacian una o dos requests a Mercado
Pago de hasta 20 s cada una, sin commit intermedio. Con ``limit=100`` una
corrida podia sostener 100 filas bloqueadas y la sesion ``idle in
transaction`` durante minutos.

La conciliacion era la peor: las filas que bloquea son ``payments``, las
mismas que toma ``find_payment_for_webhook`` en cada webhook entrante y
``get_by_appointment_locked`` en ``release_pending``. Con ``lock_timeout =
5s`` en el rol de la app (migracion ``app_role_timeouts``) y MP lento, los
webhooks de Mercado Pago y el boton "liberar turno" del panel fallaban por
timeout de lock mientras durara la corrida (regla 5; incidente 2026-09-04).

En SQLite se observa el ORDEN con eventos del engine, igual que en
``test_expiracion_sin_transaccion_abierta``: antes de la primera llamada a MP
hay un commit, y entre ese commit y la ultima llamada a MP no se ejecuta
ninguna sentencia SQL (ninguna transaccion reabierta, ningun lock tomado,
durante el HTTP).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from core.config import settings
import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from modules.payments.jobs import (
    process_webhook_inbox_batch,
    reconcile_pending_payments,
)
from modules.payments.model import WebhookInbox
from tests.integration.test_expiracion_sin_transaccion_abierta import (
    _sql_entre_el_commit_y_el_ultimo_http,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
)

CUANTOS = 3


def _mercadopago_que_registra(
    monkeypatch: pytest.MonkeyPatch, linea: list[str]
) -> None:
    """Preferencias con id propio; cada consulta de pago anota un ``http``."""
    creadas = 0

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        nonlocal creadas
        if path.startswith("/checkout/preferences"):
            creadas += 1
            return {
                "id": f"pref-b2-02-{creadas}",
                "init_point": (
                    "https://www.mercadopago.com/checkout/v1/redirect?p=b202"
                ),
            }
        linea.append("http")
        if path.startswith("/v1/payments/search"):
            return {"results": []}
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


def _escuchar(engine: AsyncEngine, linea: list[str]) -> tuple[Any, Any]:
    def sql(*args: Any, **kwargs: Any) -> None:
        linea.append("sql")

    def commit(*args: Any, **kwargs: Any) -> None:
        linea.append("commit")

    event.listen(engine.sync_engine, "before_cursor_execute", sql)
    event.listen(engine.sync_engine, "commit", commit)
    return sql, commit


def _dejar_de_escuchar(engine: AsyncEngine, sql: Any, commit: Any) -> None:
    event.remove(engine.sync_engine, "before_cursor_execute", sql)
    event.remove(engine.sync_engine, "commit", commit)


async def _tienda_con_mercadopago(client: AsyncClient, slug: str) -> tuple[str, str]:
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    return store, token


async def _reservas_con_sena_pendiente(
    client: AsyncClient, token: str, store: str, *, slug: str
) -> None:
    servicio = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    for i in range(CUANTOS):
        reserva = await client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": servicio,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=9 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": "Cliente MP",
                "client_phone": "+5491155588888",
                "payment_method": "mercadopago",
                "accepts_terms": True,
                "idempotency_key": f"{slug}-{i}",
            },
        )
        assert reserva.status_code == 201, reserva.text


@pytest.mark.asyncio
async def test_el_lote_del_inbox_corre_sin_transaccion_abierta(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    linea: list[str] = []
    _mercadopago_que_registra(monkeypatch, linea)
    _store, token = await _tienda_con_mercadopago(client, "b202-inbox")
    store_id = (await client.get("/me", headers=auth_headers(token))).json()["store_id"]
    for i in range(CUANTOS):
        test_session.add(
            WebhookInbox(
                store_id=store_id,
                provider="mercadopago",
                event_id=f"evt-b202-{i}",
                event_type="payment",
                payload={"type": "payment", "data": {"id": f"pay-b202-{i}"}},
            )
        )
    await test_session.commit()
    linea.clear()

    sql, commit = _escuchar(test_engine, linea)
    try:
        stats = await process_webhook_inbox_batch(test_session)
    finally:
        _dejar_de_escuchar(test_engine, sql, commit)

    assert stats["inspected"] == CUANTOS, stats
    assert "http" in linea, linea
    assert _sql_entre_el_commit_y_el_ultimo_http(linea) == [], (
        f"la transaccion se reabrio durante las llamadas a Mercado Pago: {linea}"
    )


@pytest.mark.asyncio
async def test_la_conciliacion_corre_sin_transaccion_abierta(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # F1-20: sin edad minima, el cobro recien creado ya es conciliable.
    monkeypatch.setattr(settings, "RECONCILIATION_MIN_AGE_MINUTES", 0)
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    linea: list[str] = []
    _mercadopago_que_registra(monkeypatch, linea)
    store, token = await _tienda_con_mercadopago(client, "b202-concilia")
    await _reservas_con_sena_pendiente(client, token, store, slug="b202-concilia")
    linea.clear()

    sql, commit = _escuchar(test_engine, linea)
    try:
        stats = await reconcile_pending_payments(test_session)
    finally:
        _dejar_de_escuchar(test_engine, sql, commit)

    assert stats["inspected"] == CUANTOS, stats
    assert "http" in linea, linea
    assert _sql_entre_el_commit_y_el_ultimo_http(linea) == [], (
        f"la transaccion se reabrio durante las llamadas a Mercado Pago: {linea}"
    )
