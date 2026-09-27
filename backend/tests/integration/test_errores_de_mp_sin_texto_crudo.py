"""Los errores de Mercado Pago no llegan con texto crudo al cliente.

2026-09-24, regla 20 de CLAUDE.md (errores neutros hacia afuera): la reserva
publica (anonima) armaba el mensaje con ``f"...: {exc}"``. Un
``MercadoPagoAPIError`` lleva hasta 400 caracteres del cuerpo que devolvio
MP, asi que ese texto llegaba tal cual a cualquiera que reservara; una tienda
sin cuenta de MP conectada respondia 502 con el texto interno de
``PaymentGatewayNotConnectedError``, y el breaker abierto exponia su nombre.
El refresh de OAuth del panel devolvia ``str(exc)`` con el mismo cuerpo.

Ahora cada caso tiene mensaje y codigo fijos; al log va solo el tipo de la
excepcion (y el status de MP si lo hay).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.circuit_breaker import CircuitBreakerOpenError
from modules.appointments.model import Appointment
from modules.payments.model import Payment
from modules.payments.service import MercadoPagoAPIError
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_mp_lento_presupuesto import (
    _REQUEST_ORIGINAL,
    _breaker_propio,
    _es_mercadopago,
    _reserva,
)
from tests.integration.test_mp_sin_transaccion_en_requests import (
    _conectar_por_oauth,
    _oauth_configurado,
    _token_oauth_que_registra,
)
from tests.integration.test_payments_hardening_and_legal import _enable_payments

MARCA = "MARCA-INTERNA-DE-MP-7f3a"


def _mp_que_responde_500(monkeypatch: pytest.MonkeyPatch) -> None:
    # Se dobla httpx por debajo del cliente de MP: el cuerpo del 500 es lo
    # que ``_perform_mercadopago_request`` copia en el MercadoPagoAPIError.
    async def request(self: Any, method: str, url: Any, **kwargs: Any) -> Any:
        if not _es_mercadopago(self, url):
            return await _REQUEST_ORIGINAL(self, method, url, **kwargs)
        return httpx.Response(
            500,
            text=f'{{"message": "{MARCA}", "cause": "internal_error"}}',
            request=httpx.Request(method, str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", request)


async def _reserva_sin_pasarela(client: AsyncClient, slug: str) -> dict[str, Any]:
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    await _enable_payments(client, token)
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
    return {
        "store_public_id": store,
        "service_id": servicio,
        "staff_id": staff,
        "starts_at": dia.replace(
            hour=10, minute=0, second=0, microsecond=0
        ).isoformat(),
        "client_name": "Cliente Sin Pasarela",
        "client_phone": "+5491155500002",
        "payment_method": "mercadopago",
        "accepts_terms": True,
        "idempotency_key": f"clave-{slug}-0001",
    }


async def _sin_turnos_ni_cobros(test_session: AsyncSession) -> None:
    test_session.expire_all()
    for modelo in (Appointment, Payment):
        total = await test_session.scalar(select(func.count()).select_from(modelo))
        assert total == 0, f"quedaron filas de {modelo.__name__} sin compensar"


@pytest.mark.asyncio
async def test_un_500_de_mp_no_llega_con_su_cuerpo_a_la_reserva_publica(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _breaker_propio(monkeypatch)
    cuerpo = await _reserva(client, "mp-500-crudo")
    _mp_que_responde_500(monkeypatch)

    res = await client.post("/public/appointments", json=cuerpo)

    assert res.status_code == 502, res.text
    assert res.json()["error_code"] == "PAYMENT_LINK_CREATION_FAILED"
    assert res.json()["message"] == "No se pudo iniciar el cobro online"
    assert MARCA not in res.text
    assert "internal_error" not in res.text
    await _sin_turnos_ni_cobros(test_session)


@pytest.mark.asyncio
async def test_el_breaker_abierto_no_expone_su_detalle_en_la_reserva_publica(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    cuerpo = await _reserva(client, "mp-breaker-crudo")

    async def abierto(*_args: Any, **_kwargs: Any) -> Any:
        raise CircuitBreakerOpenError(MARCA, retry_after_seconds=30)

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", abierto)

    res = await client.post("/public/appointments", json=cuerpo)

    assert res.status_code == 503, res.text
    assert res.json()["error_code"] == "PAYMENT_PROVIDER_UNAVAILABLE"
    assert res.json()["message"] == "Proveedor de pagos temporalmente no disponible"
    assert MARCA not in res.text
    assert "Circuit breaker" not in res.text
    await _sin_turnos_ni_cobros(test_session)


@pytest.mark.asyncio
async def test_una_tienda_sin_mp_conectado_responde_409_con_mensaje_fijo(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _breaker_propio(monkeypatch)
    # La tienda cobra senas pero nunca conecto su cuenta de Mercado Pago.
    cuerpo = await _reserva_sin_pasarela(client, "mp-sin-pasarela")

    res = await client.post("/public/appointments", json=cuerpo)

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "PAYMENT_GATEWAY_NOT_CONNECTED"
    assert res.json()["message"] == (
        "Este negocio no tiene el cobro online disponible en este momento"
    )
    assert "conectar su cuenta" not in res.text
    await _sin_turnos_ni_cobros(test_session)


@pytest.mark.asyncio
async def test_el_refresh_de_oauth_no_devuelve_el_texto_de_mp(
    client: AsyncClient,
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _oauth_configurado(monkeypatch)
    linea: list[str] = []
    _token_oauth_que_registra(monkeypatch, linea, "APP_USR-crudo")
    _store, token = await register_and_login(
        client, slug="mp-refresh-crudo", email="mp-refresh-crudo@t.com"
    )
    conectado = await _conectar_por_oauth(client, token, test_engine, linea)
    assert conectado.status_code == 303, conectado.text

    async def rechaza(form_data: dict[str, str]) -> dict[str, Any]:
        raise MercadoPagoAPIError(f'{{"error": "{MARCA}"}}', status_code=400)

    monkeypatch.setattr(payments_service, "_mercadopago_oauth_token_request", rechaza)

    res = await client.post(
        "/payments/mercadopago/oauth/refresh", headers=auth_headers(token)
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "MERCADOPAGO_REFRESH_FAILED"
    assert res.json()["message"] == (
        "No se pudo renovar la conexion con Mercado Pago. Volve a conectarla."
    )
    assert MARCA not in res.text
