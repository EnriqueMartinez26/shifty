"""Lo que se guarda de Mercado Pago es una lista blanca, no el recurso entero.

2026-09-25, L3-01 (auditoria de datos de terceros) y PV-14. La conciliacion
guardaba en ``payments.raw_payload`` el recurso completo de
``GET /v1/payments/{id}`` y ``/v1/payments/search``: email, nombre e
identificacion (DNI/CUIT) del pagador, titular y ultimos digitos de la
tarjeta. La preferencia se guardaba completa con ``payer`` e ``items``. La
Politica de Privacidad dice que Shifty no recibe ni almacena esos datos, y
ningun lector de ``raw_payload`` los usa. Se guarda solo lo que el webhook
ya elegia (``processing.enrich_mercadopago_webhook_payload``).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.service as payments_service
from core.config import settings
from modules.payments.jobs import reconcile_pending_payments
from modules.payments.model import Payment, PaymentStatus
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_payments_hardening_and_legal import (
    _book_with_mercadopago,
    _configure_gateway,
    _enable_payments,
)

DATOS_DEL_PAGADOR = {
    "payer": {
        "email": "pagador-real@example.com",
        "first_name": "Juana",
        "last_name": "Perez",
        "identification": {"type": "DNI", "number": "30123456"},
        "phone": {"area_code": "11", "number": "55556666"},
    },
    "card": {
        "first_six_digits": "450995",
        "last_four_digits": "3704",
        "cardholder": {
            "name": "JUANA PEREZ",
            "identification": {"type": "DNI", "number": "30123456"},
        },
    },
    "additional_info": {"payer": {"first_name": "Juana"}, "ip_address": "1.2.3.4"},
    "point_of_interaction": {"transaction_data": {"bank_info": {"payer": {}}}},
}

PREFERENCIA_CON_PAGADOR = {
    "id": "pref-minimizada",
    "init_point": "https://www.mercadopago.com/checkout/v1/redirect?pref=min",
    "sandbox_init_point": "https://sandbox.mercadopago.com/checkout?pref=min",
    "payer": {"name": "Juana", "email": "pagador-real@example.com"},
    "items": [{"title": "Consulta psiquiatrica", "unit_price": 3000}],
    "collector_id": 123,
    "back_urls": {"success": "https://x/ok"},
}


def _mp(monkeypatch: pytest.MonkeyPatch, remoto: dict[str, Any] | None) -> None:
    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return dict(PREFERENCIA_CON_PAGADOR)
        if path.startswith("/v1/payments/search"):
            return {"results": [remoto] if remoto else []}
        if path.startswith("/v1/payments/"):
            return remoto or {}
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


def _texto(payload: object) -> str:
    return json.dumps(payload, sort_keys=True)


async def _cobro(test_session: AsyncSession, turno: str) -> Payment:
    return (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == turno)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_la_preferencia_se_guarda_sin_pagador_ni_items(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mp(monkeypatch, None)
    store, token = await register_and_login(
        client, slug="min-pref", email="min-pref@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix="min-pref", hour=9
    )

    cobro = await _cobro(test_session, turno)
    guardado = cobro.raw_payload or {}
    assert guardado.get("id") == "pref-minimizada"
    assert guardado.get("init_point") == PREFERENCIA_CON_PAGADOR["init_point"]
    texto = _texto(guardado)
    for dato in ("pagador-real@example.com", "Juana", "psiquiatrica", "back_urls"):
        assert dato not in texto, f"{dato!r} quedo en raw_payload: {texto}"


@pytest.mark.asyncio
async def test_la_conciliacion_guarda_el_pago_sin_datos_del_pagador_ni_tarjeta(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "RECONCILIATION_MIN_AGE_MINUTES", 0)
    _mp(monkeypatch, None)
    store, token = await register_and_login(
        client, slug="min-concilia", email="min-concilia@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix="min-concilia", hour=10
    )
    cobro = await _cobro(test_session, turno)

    remoto = {
        "id": "mp-min-1",
        "status": "approved",
        "status_detail": "accredited",
        "external_reference": cobro.current_external_reference,
        "preference_id": cobro.preference_id,
        "transaction_amount": float(cobro.amount),
        "currency_id": cobro.currency,
        "date_approved": "2026-09-25T10:00:00.000-03:00",
        "metadata": {"appointment_id": turno, "notas": "dato suelto"},
        **DATOS_DEL_PAGADOR,
    }
    _mp(monkeypatch, remoto)
    stats = await reconcile_pending_payments(test_session)
    assert stats["reconciled"] == 1

    await test_session.refresh(cobro)
    assert cobro.status == PaymentStatus.APPROVED.value
    guardado = cobro.raw_payload or {}
    datos = guardado.get("data")
    assert isinstance(datos, dict), guardado
    # Lo que si se lee sigue estando.
    assert datos.get("id") == "mp-min-1"
    assert datos.get("status") == "approved"
    assert datos.get("transaction_amount") == float(cobro.amount)
    assert datos.get("external_reference") == cobro.current_external_reference
    assert datos.get("metadata") == {"appointment_id": turno}
    texto = _texto(guardado)
    for dato in (
        "pagador-real@example.com",
        "30123456",
        "3704",
        "450995",
        "JUANA PEREZ",
        "1.2.3.4",
        "payer",
        "card",
        "dato suelto",
    ):
        assert dato not in texto, f"{dato!r} quedo en raw_payload: {texto}"
