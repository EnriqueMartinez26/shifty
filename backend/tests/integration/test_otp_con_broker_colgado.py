"""Con el broker colgado, el pedido de OTP responde en menos de 2,5 s.

F1-03 (plan de rendimiento, R8-02/R9-04, 2026-09-24). Sintoma medido: con
RabbitMQ inalcanzable, ``send_otp_email.delay`` bloqueaba el event loop ~16 s
por publish (hasta 33 s), congelando la API entera, y el pedido de OTP
tardaba distinto que con el broker sano (regla 20: respuesta neutra). Ahora
el encolado corre en un hilo con tope de 2 s y la respuesta es la misma.
"""

from __future__ import annotations

import threading
import time

import pytest
from httpx import AsyncClient

import modules.notifications.tasks as tasks
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)


class _BrokerColgado:
    name = "send_otp_email"

    def __init__(self) -> None:
        self.soltar = threading.Event()

    def delay(self, *_args: object) -> None:
        self.soltar.wait(5)


@pytest.mark.asyncio
async def test_el_otp_responde_neutro_y_a_tiempo_con_el_broker_colgado(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tienda, _ = await register_and_login(
        client, slug="otp-broker-colgado", email="otp-broker-colgado@example.com"
    )
    broker = _BrokerColgado()
    monkeypatch.setattr(tasks, "send_otp_email", broker)
    try:
        inicio = time.monotonic()
        pedido = await client.post(
            "/public/otp/request",
            json={
                "store_public_id": tienda,
                "phone": "+5491155550070",
                "channel": "email",
                "email": "cliente@example.com",
            },
        )
        demora = time.monotonic() - inicio
    finally:
        broker.soltar.set()

    assert pedido.status_code == 200, pedido.text
    assert pedido.json()["ok"] is True
    assert demora < 2.5, f"el pedido de OTP tardo {demora:.2f} s"
