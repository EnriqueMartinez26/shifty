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
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.crypto import decrypt_secret
from core.config import settings
from modules.otp.model import OtpVerification
from modules.payments.model import EVENT_EMAIL_SEND, OutboxMessage
from tests.postgres.conftest import seed_store_and_admin

pytestmark = pytest.mark.postgres

TELEFONO = "5491160008888"
VICTIMA = "victima@example.com"
ATACANTE = "atacante@example.com"
_CODIGO = re.compile(r"\b\d{6}\b")


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


async def _codigo_actual_en_outbox(
    owner_engine: AsyncEngine, tienda: str, destino: str
) -> str:
    async with owner_engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    select(OutboxMessage.payload)
                    .where(
                        OutboxMessage.store_id == tienda,
                        OutboxMessage.event_type == EVENT_EMAIL_SEND,
                    )
                    .order_by(OutboxMessage.created_at, OutboxMessage.id)
                )
            )
            .scalars()
            .all()
        )
        for payload in reversed(rows):
            if not isinstance(payload, dict):
                continue
            arguments = payload.get("args")
            guard = payload.get("guard")
            if (
                not isinstance(arguments, dict)
                or not isinstance(guard, dict)
                or guard.get("kind") != "otp"
                or arguments.get("to") != destino
            ):
                continue
            otp_id = guard.get("otp_id")
            current = await conn.scalar(
                select(OtpVerification.id).where(
                    OtpVerification.id == otp_id,
                    OtpVerification.store_id == tienda,
                    OtpVerification.email == destino,
                    OtpVerification.consumed_at.is_(None),
                    OtpVerification.expires_at > datetime.now(timezone.utc),
                )
            )
            if current is None:
                continue
            encrypted_body = arguments.get("encrypted_body")
            body = decrypt_secret(
                encrypted_body if isinstance(encrypted_body, str) else None
            )
            assert body is not None
            encontrado = _CODIGO.search(body)
            assert encontrado is not None
            return encontrado.group(0)
    raise AssertionError(f"no hay un OTP vivo en el outbox para {destino}")


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
) -> None:
    tienda = await seed_store_and_admin(
        app_sessions, slug="pg-otp-destino", email="pg-otp-destino@demo.com"
    )
    assert await _pedir(client, tienda, VICTIMA) == 200
    codigo_a = await _codigo_actual_en_outbox(owner_engine, tienda, VICTIMA)
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
) -> None:
    tienda = await seed_store_and_admin(
        app_sessions, slug="pg-otp-intentos", email="pg-otp-intentos@demo.com"
    )
    assert await _pedir(client, tienda, VICTIMA) == 200
    assert await _pedir(client, tienda, ATACANTE) == 200
    codigo_a = await _codigo_actual_en_outbox(owner_engine, tienda, VICTIMA)
    codigo_b = await _codigo_actual_en_outbox(owner_engine, tienda, ATACANTE)
    errado = _otro_codigo(codigo_a, codigo_b)
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
) -> None:
    """Pedidos que reemplazan el codigo de una casilla mientras otros
    verifican: los dos lados toman las filas vivas en el mismo orden, asi que
    ninguno termina en deadlock (500)."""
    tienda = await seed_store_and_admin(
        app_sessions, slug="pg-otp-orden", email="pg-otp-orden@demo.com"
    )
    assert await _pedir(client, tienda, VICTIMA) == 200
    assert await _pedir(client, tienda, ATACANTE) == 200
    codigo_victima = await _codigo_actual_en_outbox(owner_engine, tienda, VICTIMA)
    codigo_atacante = await _codigo_actual_en_outbox(owner_engine, tienda, ATACANTE)
    errado = _otro_codigo(codigo_victima, codigo_atacante)

    estados = await asyncio.gather(
        *(_pedir(client, tienda, (VICTIMA, ATACANTE)[n % 2]) for n in range(4)),
        *(_verificar(client, tienda, errado) for _ in range(3)),
    )

    assert list(estados[:4]) == [200] * 4, estados
    assert set(estados[4:]) <= {400, 429}, estados
    assert set(await _intentos_vivos(owner_engine, tienda)) >= {VICTIMA, ATACANTE}
