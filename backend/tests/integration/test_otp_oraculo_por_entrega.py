"""AUD2-B4-05 (2026-09-20): "no me llego nada" decia que el telefono es cliente.

Sintoma: con la guarda de B4-01, si el telefono ya es de un cliente con email
entregable y el email tipeado no coincide, NADIE recibia el codigo. La
respuesta HTTP, su forma y su tiempo quedaron identicos (hay tests), pero el
atacante controla el email que tipea: pide el codigo para el telefono X con su
propia casilla y mira si llega ALGO. Si llega, X no es cliente de esa tienda;
si no llega, X si lo es. Con el mismo telefono contra varias tiendas se mapea
donde es cliente una persona, que es dato personal (mismo invariante que
motivo ``UNKNOWN_HISTORY`` en ``/public/deposit/preview``).
``OTP_MAX_REQUESTS_PER_HOUR`` acota el ritmo, no el oraculo.

Decision del coordinador: respuesta neutra tambien en el canal de entrega.
Cuando el codigo va al email de la ficha y no al tipeado, al tipeado le llega
SIEMPRE un aviso sin codigo, asi "llego algo" deja de discriminar (regla 20).
"""

from __future__ import annotations

import re

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_otp_por_email import Cola

TELEFONO_CLIENTE = "5491155551234"
TELEFONO_DESCONOCIDO = "5491166669999"
EMAIL_CLIENTE = "duenio@example.com"
EMAIL_TIPEADO = "atacante@example.com"

_CODIGO = re.compile(r"\b\d{6}\b")


def _tiene_codigo(cuerpo: str) -> bool:
    return _CODIGO.search(cuerpo) is not None


async def _tienda_con_cliente(
    client: AsyncClient, session: AsyncSession, slug: str
) -> str:
    publica, _ = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    store_id = await session.scalar(select(Store.id).where(Store.public_id == publica))
    assert store_id is not None
    session.add(
        User(
            email=EMAIL_CLIENTE,
            hashed_password="!",
            role=UserRole.CLIENT.value,
            store_id=store_id,
            phone=TELEFONO_CLIENTE,
            full_name="Duenio del telefono",
        )
    )
    await session.commit()
    return publica


async def _pedir(client: AsyncClient, tienda: str, telefono: str, email: str) -> int:
    respuesta = await client.post(
        "/public/otp/request",
        headers={"x-raw-response": "false"},
        json={
            "store_public_id": tienda,
            "phone": f"+{telefono}",
            "channel": "email",
            "email": email,
        },
    )
    return respuesta.status_code


@pytest.mark.asyncio
async def test_al_email_tipeado_le_llega_algo_sea_cliente_el_telefono_o_no(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    tienda = await _tienda_con_cliente(client, test_session, "otp-oraculo")

    assert await _pedir(client, tienda, TELEFONO_CLIENTE, EMAIL_TIPEADO) == 200
    con_cliente = [d for d, _, _ in cola.enviados if d == EMAIL_TIPEADO]
    cola.enviados.clear()
    assert await _pedir(client, tienda, TELEFONO_DESCONOCIDO, EMAIL_TIPEADO) == 200
    sin_cliente = [d for d, _, _ in cola.enviados if d == EMAIL_TIPEADO]

    # Lo que ve la casilla tipeada es lo mismo en los dos casos: un mail.
    assert con_cliente == sin_cliente == [EMAIL_TIPEADO], (
        "la llegada del mail discrimina si el telefono es cliente"
    )


@pytest.mark.asyncio
async def test_el_aviso_del_camino_retenido_no_lleva_codigo_ni_el_email_del_cliente(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    tienda = await _tienda_con_cliente(client, test_session, "otp-oraculo-cuerpo")

    assert await _pedir(client, tienda, TELEFONO_CLIENTE, EMAIL_TIPEADO) == 200

    al_tipeado = [m for m in cola.enviados if m[0] == EMAIL_TIPEADO]
    assert len(al_tipeado) == 1, "exactamente un envio al tipeado, como el feliz"
    destino, asunto, cuerpo = al_tipeado[0]
    assert destino == EMAIL_TIPEADO
    assert not _tiene_codigo(cuerpo), "el aviso sin codigo no puede traer el codigo"
    assert EMAIL_CLIENTE not in cuerpo and EMAIL_CLIENTE not in asunto
    # Mismo asunto que el codigo: el asunto tampoco discrimina.
    cola.enviados.clear()
    assert await _pedir(client, tienda, TELEFONO_DESCONOCIDO, EMAIL_TIPEADO) == 200
    assert cola.enviados[0][1] == asunto


@pytest.mark.asyncio
async def test_el_email_del_cliente_sigue_recibiendo_el_codigo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda viva de B4-01: el codigo solo va al email registrado."""
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    tienda = await _tienda_con_cliente(client, test_session, "otp-oraculo-ok")

    assert await _pedir(client, tienda, TELEFONO_CLIENTE, EMAIL_CLIENTE) == 200

    assert [d for d, _, _ in cola.enviados] == [EMAIL_CLIENTE]
    assert _tiene_codigo(cola.enviados[0][2])
