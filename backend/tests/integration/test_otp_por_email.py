"""El codigo OTP se manda por email (2026-09-10).

Hasta ahora ningun canal despachaba el codigo: solo se exponia en la
respuesta con OTP_DEBUG_EXPOSE_CODE (modo desarrollo). En produccion la
tienda que activaba "OTP en reserva publica" se quedaba sin reservas. Email
es el unico canal con envio real; whatsapp/sms quedan para desarrollo.
"""

import pytest
from httpx import AsyncClient

import modules.notifications.tasks as tasks
from core.config import settings
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)


class Buzon:
    def __init__(self, *, falla: bool = False) -> None:
        self.enviados: list[tuple[str, str, str]] = []
        self.falla = falla

    async def __call__(self, to: str, subject: str, body: str) -> bool:
        if self.falla:
            return False
        self.enviados.append((to, subject, body))
        return True


@pytest.mark.asyncio
async def test_el_codigo_llega_por_email_y_verifica(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, _ = await register_and_login(
        client, slug="otp-mail", email="otp-mail@example.com"
    )

    pedido = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store,
            "phone": "+54 9 11 5555-0042",
            "channel": "email",
            "email": "cliente@example.com",
        },
    )
    assert pedido.status_code == 200, pedido.text
    assert len(buzon.enviados) == 1
    destino, asunto, cuerpo = buzon.enviados[0]
    assert destino == "cliente@example.com"
    assert "codigo" in asunto.lower()
    codigo = pedido.json()["debug_code"]  # expuesto solo en tests/desarrollo
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


@pytest.mark.asyncio
async def test_un_smtp_caido_responde_igual_que_uno_sano(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Respuesta neutra: no revela si el telefono existe ni si el mail salio.
    monkeypatch.setattr(tasks, "_send_email", Buzon(falla=True))
    store, _ = await register_and_login(
        client, slug="otp-caido", email="otp-caido@example.com"
    )
    pedido = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store,
            "phone": "+5491155550044",
            "channel": "email",
            "email": "cliente@example.com",
        },
    )
    assert pedido.status_code == 200, pedido.text
    assert pedido.json()["ok"] is True


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
