"""Con el broker colgado, el pedido de OTP responde en menos de 2,5 s.

F1-03 (plan de rendimiento, R8-02/R9-04, 2026-09-24). Sintoma medido: con
RabbitMQ inalcanzable, ``send_otp_email.delay`` bloqueaba el event loop ~16 s
por publish (hasta 33 s), congelando la API entera, y el pedido de OTP
tardaba distinto que con el broker sano (regla 20: respuesta neutra). Ahora
el encolado corre en un hilo con tope de 2 s y la respuesta es la misma.

Revision (2026-09-24): con el codigo a la ficha y el aviso sin codigo al
email tipeado son DOS encolados; en serie costaban ~4 s contra ~2 s del
camino de un mail, y el tiempo volvia a decir si el telefono es cliente. Se
encolan a la vez: los dos caminos cuestan lo mismo.
"""

from __future__ import annotations

import threading
import time

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_otp_oraculo_por_entrega import (
    EMAIL_TIPEADO,
    TELEFONO_CLIENTE,
    _tienda_con_cliente,
)


class _BrokerColgado:
    name = "send_otp_email"

    def __init__(self) -> None:
        self.soltar = threading.Event()
        self.publicados = 0
        self._lock = threading.Lock()

    def delay(self, *_args: object) -> None:
        with self._lock:
            self.publicados += 1
        self.soltar.wait(5)


async def _pedir_con_broker_colgado(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tienda: str,
    telefono: str,
    email: str,
) -> tuple[float, int, bool]:
    broker = _BrokerColgado()
    monkeypatch.setattr(tasks, "send_otp_email", broker)
    try:
        inicio = time.monotonic()
        pedido = await client.post(
            "/public/otp/request",
            json={
                "store_public_id": tienda,
                "phone": telefono,
                "channel": "email",
                "email": email,
            },
        )
        demora = time.monotonic() - inicio
    finally:
        broker.soltar.set()
    assert pedido.status_code == 200, pedido.text
    return demora, broker.publicados, bool(pedido.json()["ok"])


@pytest.mark.asyncio
async def test_el_otp_responde_neutro_y_a_tiempo_con_el_broker_colgado(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tienda, _ = await register_and_login(
        client, slug="otp-broker-colgado", email="otp-broker-colgado@example.com"
    )

    demora, publicados, ok = await _pedir_con_broker_colgado(
        client, monkeypatch, tienda, "+5491155550070", "cliente@example.com"
    )

    assert ok is True
    assert publicados == 1
    assert demora < 2.5, f"el pedido de OTP tardo {demora:.2f} s"


@pytest.mark.asyncio
async def test_con_dos_mails_el_broker_colgado_cuesta_lo_mismo_que_con_uno(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codigo a la ficha + aviso al tipeado: dos encolados, un solo tope."""
    tienda = await _tienda_con_cliente(client, test_session, "otp-broker-dos")

    demora, publicados, ok = await _pedir_con_broker_colgado(
        client, monkeypatch, tienda, f"+{TELEFONO_CLIENTE}", EMAIL_TIPEADO
    )

    assert ok is True
    assert publicados == 2, "el camino retenido encola codigo y aviso"
    assert demora < 2.5, f"el pedido de OTP con dos mails tardo {demora:.2f} s"
