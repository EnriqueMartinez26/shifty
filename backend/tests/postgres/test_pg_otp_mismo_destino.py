"""Varios codigos OTP vivos por telefono contra Postgres real.

2026-10-05, sintoma (revision de #126): guardar un codigo nuevo consumia
todos los vivos del telefono, y sin ficha de cliente el codigo va al email
tipeado: pedir uno con la casilla propia mataba el que la victima tenia en la
suya. Ahora solo se invalida el del mismo buzon y la verificacion compara
contra todos los vivos, lockeandolos a todos. En SQLite
(``tests/integration/test_otp_invalida_solo_mismo_destino.py``) el
``FOR UPDATE`` es un no-op y los pedidos van de a uno; aca corren a la vez,
bajo RLS, para fijar que ningun intento concurrente se pierde (cada uno suma
en TODOS los codigos vivos) y que pedidos y verificaciones no se trancan.
"""

from __future__ import annotations

import asyncio
import re
import threading

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
from core.config import settings
from tests.postgres.conftest import seed_store_and_admin

pytestmark = pytest.mark.postgres

TELEFONO = "5491160008888"
VICTIMA = "victima@example.com"
ATACANTE = "atacante@example.com"
_CODIGO = re.compile(r"\b\d{6}\b")


class _Broker:
    """``send_otp_email`` que acepta todo y guarda lo encolado."""

    name = "send_otp_email"

    def __init__(self) -> None:
        self.aceptados: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def delay(self, to: str, _subject: str, body: str) -> None:
        with self._lock:
            self.aceptados.append((to, body))

    def ultimo_codigo(self, destino: str) -> str:
        cuerpos = [body for to, body in self.aceptados if to == destino]
        assert cuerpos, destino
        encontrado = _CODIGO.search(cuerpos[-1])
        assert encontrado is not None
        return encontrado.group(0)


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> _Broker:
    doble = _Broker()
    monkeypatch.setattr(tasks, "send_otp_email", doble)
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


async def _verificar(client: AsyncClient, tienda: str, codigo: str) -> int:
    respuesta = await client.post(
        "/public/otp/verify",
        json={"store_public_id": tienda, "phone": f"+{TELEFONO}", "code": codigo},
    )
    return respuesta.status_code


def _otro_codigo(*conocidos: str) -> str:
    return next(
        f"{n:06d}" for n in range(1_000_000) if f"{n:06d}" not in set(conocidos)
    )


async def _intentos_vivos(owner_engine: AsyncEngine, tienda: str) -> dict[str, int]:
    async with owner_engine.connect() as conn:
        filas = await conn.execute(
            text(
                "select email, attempts from otp_verifications "
                "where store_id = :store and phone = :phone "
                "and consumed_at is null"
            ),
            {"store": tienda, "phone": f"+{TELEFONO}"},
        )
        return {str(email): int(intentos) for email, intentos in filas.all()}


@pytest.mark.asyncio
async def test_rafaga_de_pedidos_a_otras_casillas_no_mata_el_codigo_de_la_victima(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    broker: _Broker,
) -> None:
    tienda = await seed_store_and_admin(
        app_sessions, slug="pg-otp-destino", email="pg-otp-destino@demo.com"
    )
    assert await _pedir(client, tienda, VICTIMA) == 200
    codigo_a = broker.ultimo_codigo(VICTIMA)
    otras = [f"otra{n}@example.com" for n in range(3)]

    estados = await asyncio.gather(
        *(_pedir(client, tienda, casilla) for casilla in otras),
        _pedir(client, tienda, ATACANTE),
        _verificar(client, tienda, codigo_a),
    )

    assert list(estados) == [200] * 5, estados
    assert set(await _intentos_vivos(owner_engine, tienda)) == {ATACANTE, *otras}


@pytest.mark.asyncio
async def test_intentos_concurrentes_suman_en_todos_los_codigos_vivos(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    broker: _Broker,
) -> None:
    tienda = await seed_store_and_admin(
        app_sessions, slug="pg-otp-intentos", email="pg-otp-intentos@demo.com"
    )
    assert await _pedir(client, tienda, VICTIMA) == 200
    assert await _pedir(client, tienda, ATACANTE) == 200
    codigo_a = broker.ultimo_codigo(VICTIMA)
    errado = _otro_codigo(codigo_a, broker.ultimo_codigo(ATACANTE))
    rafaga = settings.OTP_MAX_ATTEMPTS - 1

    estados = await asyncio.gather(
        *(_verificar(client, tienda, errado) for _ in range(rafaga))
    )

    assert list(estados) == [400] * rafaga
    assert await _intentos_vivos(owner_engine, tienda) == {
        VICTIMA: rafaga,
        ATACANTE: rafaga,
    }, "un intento concurrente se perdio en algun codigo"
    assert await _verificar(client, tienda, errado) == 400
    assert await _verificar(client, tienda, codigo_a) == 429


@pytest.mark.asyncio
async def test_pedidos_a_la_misma_casilla_y_verificaciones_no_se_trancan(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    broker: _Broker,
) -> None:
    """Pedidos que reemplazan el codigo de una casilla mientras otros
    verifican: los dos lados toman las filas vivas en el mismo orden, asi que
    ninguno termina en deadlock (500)."""
    tienda = await seed_store_and_admin(
        app_sessions, slug="pg-otp-orden", email="pg-otp-orden@demo.com"
    )
    assert await _pedir(client, tienda, VICTIMA) == 200
    assert await _pedir(client, tienda, ATACANTE) == 200
    errado = _otro_codigo(broker.ultimo_codigo(VICTIMA), broker.ultimo_codigo(ATACANTE))

    estados = await asyncio.gather(
        *(_pedir(client, tienda, (VICTIMA, ATACANTE)[n % 2]) for n in range(4)),
        *(_verificar(client, tienda, errado) for _ in range(3)),
    )

    assert list(estados[:4]) == [200] * 4, estados
    assert set(estados[4:]) <= {400, 429}, estados
    assert set(await _intentos_vivos(owner_engine, tienda)) >= {VICTIMA, ATACANTE}
