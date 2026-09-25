"""La conciliacion lee la configuracion del gateway una vez por tienda.

2026-09-20, AUD2-B2-06 (regla 12, N+1): ``reconcile_pending_payments``
llamaba a ``_fetch_remote_payment`` y a ``apply_mercadopago_webhook_payload``
SIN ``configs``, asi que cada cobro del lote disparaba dos SELECT sobre
``payment_gateway_configs`` (uno en ``_mercadopago_api_request_for_store`` y
otro en ``_validate_payment_integrity``). Con ``limit=100`` son hasta 200
consultas por corrida para, casi siempre, la misma fila. B2-13 (2026-09-17)
cerro esto en el lote del inbox y dejo afuera la conciliacion, que ademas ya
hace ``JOIN`` con esa tabla: la config esta a mano y se descartaba.

Sintoma medible: con N cobros pendientes de una tienda, 2N lecturas de
``payment_gateway_configs``; ahora una sola, armada con ``in_()`` antes del
``for`` y con ``store_id`` en el ``WHERE``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from core.config import settings
import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from modules.payments.jobs import reconcile_pending_payments
from modules.payments.model import Payment

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
)

COBROS = 3


def _mercadopago_con_preferencias_distintas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una preferencia propia por reserva: el cobro se resuelve sin ambiguedad."""
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
                "id": f"pref-concilia-{creadas}",
                "init_point": (
                    "https://www.mercadopago.com/checkout/v1/redirect?p=concilia"
                ),
            }
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


async def _reservas_con_sena_pendiente(
    client: AsyncClient, token: str, store: str, *, cuantas: int
) -> None:
    """``cuantas`` reservas publicas con sena por MP, un solo profesional."""
    servicio = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, servicio, email="pro-concilia-n1@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    for i in range(cuantas):
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
                "idempotency_key": f"concilia-n1-{i}",
            },
        )
        assert reserva.status_code == 201, reserva.text


def _mercadopago_con_pagos_acreditados(
    monkeypatch: pytest.MonkeyPatch, acreditados: dict[str, dict[str, Any]]
) -> None:
    """La busqueda por ``external_reference`` devuelve el pago de ESE turno."""

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/v1/payments/search"):
            referencia = parse_qs(urlparse(path).query).get("external_reference", [""])
            return {"results": [acreditados[referencia[0]]]}
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


@pytest.mark.asyncio
async def test_la_conciliacion_lee_la_config_del_gateway_una_vez_por_tienda(
    client: AsyncClient,
    test_session: AsyncSession,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # F1-20: sin edad minima, el cobro recien creado ya es conciliable.
    monkeypatch.setattr(settings, "RECONCILIATION_MIN_AGE_MINUTES", 0)
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago_con_preferencias_distintas(monkeypatch)
    store, token = await register_and_login(
        client, slug="concilia-n1", email="concilia-n1@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    await _reservas_con_sena_pendiente(client, token, store, cuantas=COBROS)

    cobros = (await test_session.execute(select(Payment))).scalars().all()
    assert len(cobros) == COBROS
    _mercadopago_con_pagos_acreditados(
        monkeypatch,
        {
            # La busqueda va por la referencia del link vigente (perf/f4-pay).
            cobro.current_external_reference: {
                "id": f"mp-remoto-{i}",
                "status": "approved",
                "external_reference": cobro.current_external_reference,
                "preference_id": cobro.preference_id,
                "transaction_amount": float(cobro.amount),
                "currency_id": cobro.currency,
            }
            for i, cobro in enumerate(cobros)
        },
    )

    lecturas: list[str] = []

    def contar(
        conn: Any, cursor: Any, statement: str, *args: Any, **kwargs: Any
    ) -> None:
        # Solo las lecturas de la tabla en si: la consulta del lote tambien la
        # nombra, pero ahi es el JOIN que elige los cobros a conciliar.
        if "FROM payment_gateway_configs" in statement:
            lecturas.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", contar)
    try:
        resultado = await reconcile_pending_payments(test_session)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", contar)

    assert resultado["inspected"] == COBROS, resultado
    # Se aplicaron de verdad: la lectura del lote alcanzo para consultar a MP
    # Y para validar la integridad de cada cobro.
    assert resultado["reconciled"] == COBROS, resultado
    assert len(lecturas) == 1, f"{len(lecturas)} lecturas para {COBROS} cobros"
    # Guarda de tenancy (CLAUDE.md §2): la unica lectura sigue filtrando por
    # store_id, ahora con in_() sobre las tiendas del lote.
    assert "payment_gateway_configs.store_id IN" in lecturas[0]
