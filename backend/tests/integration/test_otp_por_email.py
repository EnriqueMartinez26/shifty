"""El codigo OTP se manda por email (2026-09-10).

Hasta ahora ningun canal despachaba el codigo: solo se exponia en la
respuesta con OTP_DEBUG_EXPOSE_CODE (modo desarrollo). En produccion la
tienda que activaba "OTP en reserva publica" se quedaba sin reservas. Email
es el unico canal con envio real; whatsapp/sms quedan para desarrollo.
"""

from datetime import datetime, timezone, tzinfo
from typing import Any

import pytest
from httpx import AsyncClient
from structlog.testing import capture_logs

import modules.notifications.tasks as tasks
import modules.otp.service as otp_service
from core.config import settings
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)


class Cola:
    """Reemplaza la tarea de Celery ``send_otp_email``: guarda lo encolado.

    AUD2-B4-06 (2026-09-20): el mail del OTP lo manda el worker, no el
    proceso de la API. En los tests alcanza con ver QUE se encolo, y se
    guarda con la misma forma (destino, asunto, cuerpo) que usa el sink SMTP,
    asi las aserciones son las mismas de los dos lados.
    """

    def __init__(self) -> None:
        self.enviados: list[tuple[str, str, str]] = []

    def delay(self, to: str, subject: str, body: str) -> None:
        self.enviados.append((to, subject, body))


@pytest.mark.asyncio
async def test_el_codigo_llega_por_email_y_verifica(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    store, _ = await register_and_login(
        client, slug="otp-mail", email="otp-mail@example.com"
    )

    pedido = await client.post(
        "/public/otp/request",
        headers={"x-raw-response": "false"},
        json={
            "store_public_id": store,
            "phone": "+54 9 11 5555-0042",
            "channel": "email",
            "email": "cliente@example.com",
        },
    )
    assert pedido.status_code == 200, pedido.text
    assert len(cola.enviados) == 1
    destino, asunto, cuerpo = cola.enviados[0]
    assert destino == "cliente@example.com"
    assert "codigo" in asunto.lower()
    codigo = pedido.json()["data"]["debug_code"]  # solo en tests/desarrollo
    assert codigo in cuerpo

    verificado = await client.post(
        "/public/otp/verify",
        json={"store_public_id": store, "phone": "+5491155550042", "code": codigo},
    )
    assert verificado.status_code == 200, verificado.text
    assert verificado.json()["ok"] is True


@pytest.mark.asyncio
async def test_sin_email_el_canal_email_es_422(client: AsyncClient) -> None:
    store, _ = await register_and_login(
        client, slug="otp-sin", email="otp-sin@example.com"
    )
    pedido = await client.post(
        "/public/otp/request",
        json={"store_public_id": store, "phone": "+5491155550043", "channel": "email"},
    )
    assert pedido.status_code == 422, pedido.text


class _ColaCaida:
    """Broker caido: el unico fallo de envio que el request puede ver hoy."""

    def delay(self, *_args: object) -> None:
        raise RuntimeError("broker caido")


class _RelojQuieto:
    """Solo ``now``: es lo unico del reloj que usa el camino del pedido."""

    @staticmethod
    def now(tz: tzinfo | None = None) -> datetime:
        return datetime(2026, 9, 20, 12, 0, tzinfo=tz)


@pytest.mark.asyncio
async def test_un_fallo_de_envio_responde_byte_a_byte_igual_que_el_camino_sano(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AUD2-B4-11 (2026-09-20): el test anterior ya no probaba lo que decia.

    Sintoma: ``test_un_smtp_caido_responde_igual_que_uno_sano`` afirmaba
    200 + ``ok: true`` con un ``Buzon`` que fallaba sobre ``_send_email``.
    Desde B4-01 el envio salio del request y desde AUD2-B4-06 sale del
    proceso, asi que esas dos aserciones eran verdaderas por construccion y
    a su ``Buzon`` no lo llamaba nadie (se verifico haciendolo reventar: el
    test seguia verde). Daba cobertura aparente al invariante "respuesta
    neutra ante fallo de envio" sin discriminar nada.

    Hoy el fallo de envio que SI puede ver el request es el del encolado.
    Con el reloj y el codigo de debug quietos, lo unico que podria cambiar
    entre las dos respuestas es lo que este test quiere vigilar: que el
    sobre canonico sea identico byte a byte y que el fallo quede en el log
    sin datos personales.
    """
    monkeypatch.setattr(otp_service, "datetime", _RelojQuieto)
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", False)
    store, _ = await register_and_login(
        client, slug="otp-caido", email="otp-caido@example.com"
    )

    async def pedir() -> Any:
        return await client.post(
            "/public/otp/request",
            headers={"x-raw-response": "false"},
            json={
                "store_public_id": store,
                "phone": "+5491155550044",
                "channel": "email",
                "email": "cliente@example.com",
            },
        )

    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    sano = await pedir()
    monkeypatch.setattr(tasks, "send_otp_email", _ColaCaida())
    with capture_logs() as eventos:
        caido = await pedir()

    assert sano.status_code == 200, sano.text
    assert sano.json()["data"]["ok"] is True
    assert len(cola.enviados) == 1, "el camino sano encola exactamente un mail"
    assert caido.status_code == sano.status_code, caido.text
    assert caido.content == sano.content, "la respuesta cambia cuando falla el envio"
    assert caido.headers["content-type"] == sano.headers["content-type"]

    assert any(e["event"] == "otp_email_enqueue_failed" for e in eventos)
    # F1-03: el tipo de error lo registra el helper unico de encolado.
    aviso = next(e for e in eventos if e["event"] == "enqueue_failed")
    assert aviso["error_type"] == "RuntimeError"
    assert "cliente@example.com" not in str(aviso)
    assert "5555" not in str(aviso)


@pytest.mark.asyncio
async def test_whatsapp_y_sms_solo_existen_en_modo_consola(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = await register_and_login(
        client, slug="otp-canal", email="otp-canal@example.com"
    )
    # En desarrollo (console) siguen aceptandose, con el codigo visible.
    dev = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store,
            "phone": "+5491155550045",
            "channel": "whatsapp",
        },
    )
    assert dev.status_code == 200, dev.text

    # Con un proveedor "real" declarado pero sin despacho implementado, se
    # rechaza en vez de dejar al cliente esperando un codigo que no llega.
    monkeypatch.setattr(settings, "OTP_PROVIDER", "twilio")
    prod = await client.post(
        "/public/otp/request",
        json={"store_public_id": store, "phone": "+5491155550046", "channel": "sms"},
    )
    assert prod.status_code == 422, prod.text
