"""AUD2-B4-06 (2026-09-20): el OTP se encola, no corre dentro del request.

Sintoma: B4-01 saco el envio del camino sincronico con
``BackgroundTasks.add_task``, que NO sale del proceso. El SMTP corria dentro
de la misma llamada ASGI -despues de mandar los bytes de la respuesta, pero
antes de terminar el request-, asi que un SMTP colgado retenia el slot los
10 s de timeout por pedido (conexion + STARTTLS + LOGIN + DATA); el rate
limit acota por IP y por telefono, no globalmente. Y no habia rastro
durable: si el proceso se reiniciaba entre la respuesta y el envio, el
cliente se quedaba esperando un codigo que ya estaba guardado en la base.

Decision del coordinador: el OTP se despacha por Celery. El request solo
encola; el mail lo manda el worker, por el sink SMTP unico de siempre.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

import modules.notifications.tasks as tasks
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_otp_por_email import Cola


async def _pedir(client: AsyncClient, tienda: str, telefono: str) -> Any:
    return await client.post(
        "/public/otp/request",
        json={
            "store_public_id": tienda,
            "phone": telefono,
            "channel": "email",
            "email": "cliente@example.com",
        },
    )


@pytest.mark.asyncio
async def test_el_pedido_encola_el_mail_y_no_toca_el_smtp_en_el_proceso_de_la_api(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    cola = Cola()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    tienda, _ = await register_and_login(
        client, slug="otp-cola", email="otp-cola@example.com"
    )

    pedido = await _pedir(client, tienda, "+5491155550060")

    assert pedido.status_code == 200, pedido.text
    # Ni durante el request ni despues de la respuesta: el proceso de la API
    # no abre la conexion SMTP.
    assert buzon.enviados == [], "el SMTP corrio dentro de la llamada ASGI"
    assert [destino for destino, _, _ in cola.enviados] == ["cliente@example.com"]
    # El fixture ``client`` pide el recurso pelado (``x-raw-response: true``).
    codigo = pedido.json()["debug_code"]
    assert codigo in cola.enviados[0][2]


@pytest.mark.asyncio
async def test_la_tarea_manda_por_el_sink_unico_de_correo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El cuerpo de la tarea (lo que corre en el worker) usa ``_send_email``.

    Se prueba la corrutina y no el wrapper de Celery porque el wrapper entra
    por ``run_in_worker_loop``, que se niega a anidarse en un loop activo.
    """
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)

    assert await tasks.deliver_otp_email("a@example.com", "Asunto", "Cuerpo") == {
        "status": "sent"
    }
    assert buzon.enviados == [("a@example.com", "Asunto", "Cuerpo")]

    monkeypatch.setattr(tasks, "_send_email", Buzon(falla=True))
    assert await tasks.deliver_otp_email("a@example.com", "Asunto", "Cuerpo") == {
        "status": "failed"
    }


@pytest.mark.asyncio
async def test_un_broker_caido_no_cambia_la_respuesta_del_otp(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fallo de encolado = fallo de envio: se loguea, no se propaga.

    La respuesta del OTP es neutra por contrato (regla 20): no puede empezar
    a devolver 500 -ni tardar distinto- porque el broker este caido.
    """

    class ColaCaida:
        def delay(self, *_args: object) -> None:
            raise RuntimeError("broker caido")

    monkeypatch.setattr(tasks, "send_otp_email", ColaCaida())
    tienda, _ = await register_and_login(
        client, slug="otp-cola-caida", email="otp-cola-caida@example.com"
    )

    pedido = await _pedir(client, tienda, "+5491155550061")

    assert pedido.status_code == 200, pedido.text
    assert pedido.json()["ok"] is True
