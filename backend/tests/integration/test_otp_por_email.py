"""El codigo OTP se manda por email (2026-09-10).

Hasta ahora ningun canal despachaba el codigo: solo se exponia en la
respuesta con OTP_DEBUG_EXPOSE_CODE (modo desarrollo). En produccion la
tienda que activaba "OTP en reserva publica" se quedaba sin reservas. Email
es el unico canal con envio real; whatsapp/sms quedan para desarrollo.
"""

from datetime import datetime, timezone, tzinfo
from contextvars import ContextVar
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import modules.notifications.tasks as tasks
import modules.otp.service as otp_service
from core.config import settings
from core.crypto import decrypt_secret
from modules.payments.model import EVENT_EMAIL_SEND, OutboxMessage
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)


def _es_mail_otp(mensaje: OutboxMessage) -> bool:
    argumentos = mensaje.payload.get("args")
    return isinstance(argumentos, dict) and str(
        argumentos.get("subject", "")
    ).startswith("Tu código de verificación")


@pytest.mark.asyncio
async def test_el_codigo_se_guarda_cifrado_y_verifica(
    client: AsyncClient, test_session: AsyncSession
) -> None:
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
    codigo = pedido.json()["data"]["debug_code"]  # solo en tests/desarrollo
    mensajes = (
        await test_session.scalars(
            select(OutboxMessage).where(OutboxMessage.event_type == EVENT_EMAIL_SEND)
        )
    ).all()
    mensajes_otp = [mensaje for mensaje in mensajes if _es_mail_otp(mensaje)]
    assert len(mensajes_otp) == 1
    argumentos = mensajes_otp[0].payload["args"]
    assert isinstance(argumentos, dict)
    assert argumentos.get("to") == "cliente@example.com"
    assert argumentos.get("priority") == "critical"
    cuerpo = decrypt_secret(str(argumentos.get("encrypted_body", "")))
    assert cuerpo is not None and codigo in cuerpo
    assert codigo not in str(mensajes_otp[0].payload)

    verificado = await client.post(
        "/public/otp/verify",
        json={"store_public_id": store, "phone": "+5491155550042", "code": codigo},
    )
    assert verificado.status_code == 200, verificado.text
    client.headers["X-Client-Token"] = verificado.json()["client_token"]
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


class _RelojQuieto:
    """Solo ``now``: es lo unico del reloj que usa el camino del pedido."""

    @staticmethod
    def now(tz: tzinfo | None = None) -> datetime:
        return datetime(2026, 9, 20, 12, 0, tzinfo=tz)


@pytest.mark.asyncio
async def test_smtp_no_se_invoca_y_el_outbox_persiste_el_mail_cifrado(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El request confirma el outbox cifrado sin abrir SMTP ni depender del broker."""
    monkeypatch.setattr(otp_service, "datetime", _RelojQuieto)
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", False)

    async def smtp_en_request(*_args: Any, **_kwargs: Any) -> bool:
        raise AssertionError("la API no debe abrir SMTP")

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

    with monkeypatch.context() as parche:
        parche.setattr(tasks, "_send_email", smtp_en_request)
        primera = await pedir()
        segunda = await pedir()

    assert primera.status_code == 200, primera.text
    assert primera.json()["data"]["ok"] is True
    assert segunda.status_code == primera.status_code, segunda.text
    assert segunda.content == primera.content, "el envio diferido cambio la respuesta"
    assert segunda.headers["content-type"] == primera.headers["content-type"]
    assert "debug_code" not in primera.json()["data"]
    mensajes = (
        await test_session.scalars(
            select(OutboxMessage).where(OutboxMessage.event_type == EVENT_EMAIL_SEND)
        )
    ).all()
    mensajes_otp = [mensaje for mensaje in mensajes if _es_mail_otp(mensaje)]
    assert len(mensajes_otp) == 2
    assert all(
        "cliente@example.com" in str(mensaje.payload) for mensaje in mensajes_otp
    )


class Cola:
    """Colector de pruebas de mensajes OTP confirmados en el outbox."""

    def __init__(self) -> None:
        self.enviados: list[tuple[str, str, str]] = []
        self._pendientes: dict[int, list[OutboxMessage]] = {}
        self._vistos: set[str] = set()
        _COLA_ACTIVA.set(self)


_COLA_ACTIVA: ContextVar[Cola | None] = ContextVar("otp_outbox_test_sink", default=None)


@event.listens_for(Session, "after_flush")
def _registrar_outbox_otp(session: Session, *_args: Any) -> None:
    cola = _COLA_ACTIVA.get()
    if cola is None:
        return
    pendientes = cola._pendientes.setdefault(id(session), [])
    for fila in session.new:
        if (
            isinstance(fila, OutboxMessage)
            and fila.event_type == EVENT_EMAIL_SEND
            and fila.id not in cola._vistos
        ):
            cola._vistos.add(fila.id)
            pendientes.append(fila)


@event.listens_for(Session, "after_commit")
def _confirmar_outbox_otp(session: Session) -> None:
    cola = _COLA_ACTIVA.get()
    if cola is None:
        return
    for fila in cola._pendientes.pop(id(session), []):
        argumentos = fila.payload.get("args")
        if (
            fila.payload.get("mail") != "encrypted_body"
            or not isinstance(argumentos, dict)
            or not str(argumentos.get("subject", "")).startswith(
                "Tu código de verificación"
            )
        ):
            continue
        cuerpo = decrypt_secret(str(argumentos.get("encrypted_body", "")))
        if cuerpo is not None:
            cola.enviados.append(
                (
                    str(argumentos.get("to")),
                    str(argumentos.get("subject")),
                    cuerpo,
                )
            )


@event.listens_for(Session, "after_rollback")
def _descartar_outbox_otp(session: Session) -> None:
    cola = _COLA_ACTIVA.get()
    if cola is not None:
        cola._pendientes.pop(id(session), None)


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
