"""El OTP persiste sus mails en outbox sin llamar al broker desde la API."""

from __future__ import annotations

from collections.abc import Iterable
import time

import pytest
from httpx import AsyncClient
from sqlalchemy import select
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
from modules.payments.model import EVENT_EMAIL_SEND, OutboxMessage
from modules.stores.model import Store


class _BrokerColgado:
    name = "send_otp_email"

    def __init__(self) -> None:
        self.publicados = 0

    def delay(self, *_args: object) -> None:
        self.publicados += 1
        raise AssertionError("el pedido de OTP no debe publicar al broker")


async def _pedir_con_broker_colgado(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tienda: str,
    telefono: str,
    email: str,
) -> tuple[float, int, bool]:
    broker = _BrokerColgado()
    monkeypatch.setattr(tasks, "send_otp_email", broker)
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
    assert pedido.status_code == 200, pedido.text
    return demora, broker.publicados, bool(pedido.json()["ok"])


@pytest.mark.asyncio
async def test_el_otp_responde_neutro_y_a_tiempo_con_el_broker_colgado(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tienda, _ = await register_and_login(
        client, slug="otp-broker-colgado", email="otp-broker-colgado@example.com"
    )

    demora, publicados, ok = await _pedir_con_broker_colgado(
        client, monkeypatch, tienda, "+5491155550070", "cliente@example.com"
    )

    assert ok is True
    assert publicados == 0
    assert demora < 2.5, f"el pedido de OTP tardo {demora:.2f} s"
    store = (
        await test_session.scalars(select(Store).where(Store.public_id == tienda))
    ).one()
    mensajes = (
        await test_session.scalars(
            select(OutboxMessage).where(
                OutboxMessage.event_type == EVENT_EMAIL_SEND,
                OutboxMessage.store_id == store.id,
            )
        )
    ).all()
    assert len(_mensajes_otp(mensajes)) == 1


@pytest.mark.asyncio
async def test_con_dos_mails_el_broker_colgado_cuesta_lo_mismo_que_con_uno(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codigo a la ficha + aviso al tipeado: dos filas, un solo tope."""
    tienda = await _tienda_con_cliente(client, test_session, "otp-broker-dos")

    demora, publicados, ok = await _pedir_con_broker_colgado(
        client, monkeypatch, tienda, f"+{TELEFONO_CLIENTE}", EMAIL_TIPEADO
    )

    assert ok is True
    assert publicados == 0
    assert demora < 2.5, f"el pedido de OTP con dos mails tardo {demora:.2f} s"
    store = (
        await test_session.scalars(select(Store).where(Store.public_id == tienda))
    ).one()
    mensajes = (
        await test_session.scalars(
            select(OutboxMessage).where(
                OutboxMessage.event_type == EVENT_EMAIL_SEND,
                OutboxMessage.store_id == store.id,
            )
        )
    ).all()
    assert len(_mensajes_otp(mensajes)) == 2


def _mensajes_otp(mensajes: Iterable[OutboxMessage]) -> list[OutboxMessage]:
    resultado = []
    for mensaje in mensajes:
        argumentos = mensaje.payload.get("args")
        if (
            mensaje.payload.get("mail") == "encrypted_body"
            and isinstance(argumentos, dict)
            and str(argumentos.get("subject", "")).startswith(
                "Tu código de verificación"
            )
        ):
            resultado.append(mensaje)
    return resultado
