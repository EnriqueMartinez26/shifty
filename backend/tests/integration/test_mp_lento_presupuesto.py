"""Mercado Pago lento: la reserva compensa dentro del presupuesto.

2026-09-24, F1-04 (R8-01, R11-08): el cliente httpx de MP tenia 20 s por
request y la reserva podia encadenar preferencia + refresh OAuth + reintento,
mas que los 30 s de nginx. El cliente veia 504 mientras el backend
commiteaba; el reintento con la misma clave chocaba 409 contra su propia
reserva. Ademas un ``TimeoutError`` de asyncio no es ``RuntimeError`` y
``_attach_payment_link`` no lo compensaba: el turno quedaba retenido sin link.

Ahora la cadena de MP de un request tiene un presupuesto total (<25 s) que
se hace cumplir por debajo del circuit breaker, y agotarlo es
``MercadoPagoAPIError(transient=True)``: se compensa como cualquier fallo del
proveedor.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.circuit_breaker import AsyncCircuitBreaker
from core.config import settings
from core.idempotency import PROCESSING_TTL_MS
from modules.appointments.model import Appointment
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

MP_LENTO_SEGUNDOS = 25.0
PRESUPUESTO_DE_PRUEBA = 0.5
_REQUEST_ORIGINAL = httpx.AsyncClient.request


def _es_mercadopago(cliente: Any, url: Any) -> bool:
    base = settings.MERCADOPAGO_API_BASE_URL
    return str(url).startswith(base) or str(cliente.base_url).startswith(base)


def _mp_que_tarda(monkeypatch: pytest.MonkeyPatch, segundos: float) -> None:
    # Se dobla httpx por debajo del cliente de MP (el test no conoce como se
    # arma): el cliente ASGI del test tambien es httpx y sigue de largo.
    original = _REQUEST_ORIGINAL

    async def request(self: Any, method: str, url: Any, **kwargs: Any) -> Any:
        if not _es_mercadopago(self, url):
            return await original(self, method, url, **kwargs)
        await asyncio.sleep(segundos)
        return httpx.Response(
            201,
            json={
                "id": "pref-lenta",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=l",
            },
            request=httpx.Request(method, str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", request)


def _breaker_propio(monkeypatch: pytest.MonkeyPatch) -> None:
    # El breaker es global del proceso: un fallo transitorio de este test no
    # puede abrirlo para los demas.
    monkeypatch.setattr(
        payments_service,
        "_mercadopago_breaker",
        AsyncCircuitBreaker(
            name="mercadopago-test", failure_threshold=50, recovery_timeout_seconds=30
        ),
    )


async def _reserva(client: AsyncClient, slug: str) -> dict[str, Any]:
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
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
        "client_name": "Cliente Lento",
        "client_phone": "+5491155500001",
        "payment_method": "mercadopago",
        "accepts_terms": True,
        "idempotency_key": f"clave-{slug}-0001",
    }


async def _turnos(test_session: AsyncSession, clave: str) -> int:
    return int(
        (
            await test_session.execute(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.idempotency_key == clave)
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_mp_lento_compensa_dentro_del_presupuesto_y_el_reintento_reserva(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _breaker_propio(monkeypatch)
    cuerpo = await _reserva(client, "mp-lento")
    monkeypatch.setattr(
        settings, "MERCADOPAGO_REQUEST_BUDGET_SECONDS", PRESUPUESTO_DE_PRUEBA
    )
    _mp_que_tarda(monkeypatch, MP_LENTO_SEGUNDOS)

    inicio = time.monotonic()
    respuesta = await client.post("/public/appointments", json=cuerpo)
    demora = time.monotonic() - inicio

    assert demora < PRESUPUESTO_DE_PRUEBA + 5, f"la reserva tardo {demora:.1f}s"
    # Respuesta controlada del proveedor (no un 500 ni un 504 del proxy).
    assert respuesta.status_code == 502, respuesta.text
    assert respuesta.json()["error_code"] == "PAYMENT_LINK_CREATION_FAILED"
    # Compensada: ni turno retenido ni cobro con link huerfano.
    assert await _turnos(test_session, cuerpo["idempotency_key"]) == 0
    cobros = (
        await test_session.execute(select(func.count()).select_from(Payment))
    ).scalar_one()
    assert cobros == 0

    # El reintento con la MISMA clave no choca 409 contra su propia reserva.
    _mp_que_tarda(monkeypatch, 0)
    reintento = await client.post("/public/appointments", json=cuerpo)
    assert reintento.status_code == 201, reintento.text
    assert reintento.json()["payment_link"].startswith("https://www.mercadopago.com/")
    assert await _turnos(test_session, cuerpo["idempotency_key"]) == 1


def test_timeouts_del_cliente_http_de_mp() -> None:
    timeout = payments_service.MERCADOPAGO_HTTP_TIMEOUT
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (
        3.0,
        10.0,
        5.0,
        3.0,
    )


def test_el_presupuesto_queda_bajo_nginx_y_la_idempotencia_lo_cubre() -> None:
    # nginx corta a los 30 s: el presupuesto de MP deja margen para la base y
    # la compensacion.
    assert settings.MERCADOPAGO_REQUEST_BUDGET_SECONDS < 25
    # La clave en PROCESSING no puede vencer con la reserva todavia en curso:
    # presupuesto de MP + mail en linea (SMTP con timeout de 10 s por
    # operacion) + margen.
    assert PROCESSING_TTL_MS / 1000 >= settings.MERCADOPAGO_REQUEST_BUDGET_SECONDS + 30


@pytest.mark.asyncio
async def test_el_cliente_http_de_mp_es_compartido_y_se_cierra() -> None:
    primero = payments_service._mercadopago_http_client()
    segundo = payments_service._mercadopago_http_client()
    assert primero is segundo
    await payments_service.close_mercadopago_client()
    assert primero.is_closed
    tercero = payments_service._mercadopago_http_client()
    assert tercero is not primero
    await payments_service.close_mercadopago_client()


@pytest.mark.asyncio
async def test_cada_event_loop_tiene_su_cliente() -> None:
    """Celery corre un loop por proceso (regla 8): un cliente de otro loop
    tiene conexiones atadas a ese loop y no se reusa."""
    del_test = payments_service._mercadopago_http_client()

    def en_otro_loop() -> Any:
        async def pedir() -> Any:
            cliente = payments_service._mercadopago_http_client()
            await payments_service.close_mercadopago_client()
            return cliente

        return asyncio.run(pedir())

    del_otro = await asyncio.to_thread(en_otro_loop)
    assert del_otro is not del_test
    await del_test.aclose()
