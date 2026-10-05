"""Rafaga de pedidos de OTP sin entrega contra Postgres real: el codigo vivo sigue.

2026-10-05, sintoma: ``request_code`` guardaba el codigo nuevo (y con eso
consumia el vivo) antes de encolar su mail; con el broker caido o el buzon
topeado, pedir codigos para un telefono ajeno dejaba al titular sin codigo
valido. En SQLite (``tests/integration/test_otp_no_pisa_codigo_sin_mail.py``)
los pedidos van de a uno; aca corren a la vez, cada uno con su sesion, bajo
RLS y con el ``UPDATE`` que invalida el vivo compitiendo de verdad.
"""

from __future__ import annotations

import asyncio
import re
import threading
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
import modules.otp.service as otp_service
from tests.postgres.conftest import seed_store_and_admin

pytestmark = pytest.mark.postgres

TELEFONO = "5491160004321"
TITULAR = "titular@example.com"
TOPEADO = "tope@example.com"
SIN_BROKER = "caido@example.com"
NUEVO = "nuevo@example.com"
_CODIGO = re.compile(r"\b\d{6}\b")


class _Broker:
    """Acepta todo menos ``SIN_BROKER``, que ve el broker caido."""

    name = "send_otp_email"

    def __init__(self) -> None:
        self.aceptados: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def delay(self, to: str, _subject: str, body: str) -> None:
        if to == SIN_BROKER:
            raise ConnectionError("broker down")
        with self._lock:
            self.aceptados.append((to, body))

    def codigo_para(self, destino: str) -> str:
        cuerpos = [body for to, body in self.aceptados if to == destino]
        assert len(cuerpos) == 1, (destino, len(cuerpos))
        encontrado = _CODIGO.search(cuerpos[0])
        assert encontrado is not None
        return encontrado.group(0)


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> _Broker:
    doble = _Broker()
    monkeypatch.setattr(tasks, "send_otp_email", doble)

    async def tope(destino: str) -> bool:
        return destino != TOPEADO

    monkeypatch.setattr(otp_service, "_destination_allows_mail", tope)
    return doble


async def _pedir(client: AsyncClient, tienda: str, email: str) -> int:
    respuesta = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": tienda,
            "phone": f"+{TELEFONO}",
            "channel": "email",
            "email": email,
        },
    )
    return respuesta.status_code


async def _verifica(client: AsyncClient, tienda: str, codigo: str) -> bool:
    respuesta = await client.post(
        "/public/otp/verify",
        json={"store_public_id": tienda, "phone": f"+{TELEFONO}", "code": codigo},
    )
    assert respuesta.status_code in {200, 400}, respuesta.text
    return respuesta.status_code == 200


async def _filas(owner_engine: AsyncEngine, tienda: str) -> int:
    async with owner_engine.connect() as conn:
        total = (
            await conn.execute(
                text(
                    "select count(*) from otp_verifications "
                    "where store_id = :store and phone = :phone"
                ),
                {"store": tienda, "phone": f"+{TELEFONO}"},
            )
        ).scalar_one()
        return cast(int, total)


@pytest.mark.asyncio
async def test_rafaga_sin_entrega_no_toca_el_codigo_vivo(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    broker: _Broker,
) -> None:
    tienda = await seed_store_and_admin(
        app_sessions, slug="pg-otp-sin-entrega", email="pg-otp-sin-entrega@demo.com"
    )
    assert await _pedir(client, tienda, TITULAR) == 200
    codigo_a = broker.codigo_para(TITULAR)

    estados = await asyncio.gather(
        *(_pedir(client, tienda, (TOPEADO, SIN_BROKER)[n % 2]) for n in range(8))
    )

    assert estados == [200] * 8
    assert await _filas(owner_engine, tienda) == 1, "un pedido sin mail guardo"
    assert await _verifica(client, tienda, codigo_a)


@pytest.mark.asyncio
async def test_entre_pedidos_sin_entrega_gana_el_que_si_encolo(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    broker: _Broker,
) -> None:
    tienda = await seed_store_and_admin(
        app_sessions, slug="pg-otp-gana-encolado", email="pg-otp-gana@demo.com"
    )
    assert await _pedir(client, tienda, TITULAR) == 200
    codigo_a = broker.codigo_para(TITULAR)

    estados = await asyncio.gather(
        _pedir(client, tienda, TOPEADO),
        _pedir(client, tienda, SIN_BROKER),
        _pedir(client, tienda, NUEVO),
        _pedir(client, tienda, SIN_BROKER),
    )

    assert list(estados) == [200] * 4
    assert await _filas(owner_engine, tienda) == 2
    codigo_b = broker.codigo_para(NUEVO)
    # 2026-10-05: el codigo nuevo fue a OTRA casilla, asi que el del titular
    # sigue vivo (``test_otp_invalida_solo_mismo_destino.py``); verifican los
    # dos, cada uno contra su buzon.
    assert await _verifica(client, tienda, codigo_b)
    if codigo_b != codigo_a:  # 1 en 10^6 de que coincidan
        assert await _verifica(client, tienda, codigo_a)
