"""Rafaga de pedidos OTP contra Postgres: el codigo vivo queda en el outbox.

La creacion del OTP y su email cifrado es transaccional. Si el destino supera
su cuota no se guarda un codigo imposible de entregar; para los destinos
admitidos, varios pedidos simultaneos conservan un email durable por intento y
solo el ultimo codigo del mismo buzon sigue vigente.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.crypto import decrypt_secret
import modules.otp.service as otp_service
from modules.otp.model import OtpVerification
from modules.payments.model import EVENT_EMAIL_SEND, OutboxMessage
from tests.postgres.conftest import seed_store_and_admin

pytestmark = pytest.mark.postgres

TELEFONO = "5491160004321"
TITULAR = "titular@example.com"
TOPEADO = "tope@example.com"
OTRA_CASILLA = "caido@example.com"
NUEVO = "nuevo@example.com"
_CODIGO = re.compile(r"\b\d{6}\b")


@pytest.fixture
def destino_topeado(monkeypatch: pytest.MonkeyPatch) -> None:
    async def tope(destino: str) -> bool:
        return destino != TOPEADO

    monkeypatch.setattr(otp_service, "_destination_allows_mail", tope)


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


async def _filas_otp(owner_engine: AsyncEngine, tienda: str) -> int:
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


async def _filas_emails_otp(owner_engine: AsyncEngine, tienda: str) -> int:
    async with owner_engine.connect() as conn:
        total = await conn.scalar(
            select(func.count(OutboxMessage.id)).where(
                OutboxMessage.store_id == tienda,
                OutboxMessage.event_type == EVENT_EMAIL_SEND,
            )
        )
        return cast(int, total)


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


@pytest.mark.asyncio
async def test_rafaga_con_tope_preserva_codigo_vivo_y_persiste_los_admitidos(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    destino_topeado: None,
) -> None:
    tienda = await seed_store_and_admin(
        app_sessions, slug="pg-otp-sin-entrega", email="pg-otp-sin-entrega@demo.com"
    )
    assert await _pedir(client, tienda, TITULAR) == 200
    codigo_titular = await _codigo_actual_en_outbox(owner_engine, tienda, TITULAR)

    estados = await asyncio.gather(
        *(_pedir(client, tienda, (TOPEADO, OTRA_CASILLA)[n % 2]) for n in range(8))
    )

    assert estados == [200] * 8
    # Cuatro pedidos fueron bloqueados por cuota antes de guardar el OTP; los
    # otros cuatro quedaron junto con sus emails cifrados en el outbox.
    assert await _filas_otp(owner_engine, tienda) == 5
    assert await _filas_emails_otp(owner_engine, tienda) == 5
    codigo_otra_casilla = await _codigo_actual_en_outbox(
        owner_engine, tienda, OTRA_CASILLA
    )
    assert await _verifica(client, tienda, codigo_titular)
    assert await _verifica(client, tienda, codigo_otra_casilla)


@pytest.mark.asyncio
async def test_pedidos_con_outbox_reemplazan_solo_el_codigo_del_mismo_destino(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    destino_topeado: None,
) -> None:
    tienda = await seed_store_and_admin(
        app_sessions, slug="pg-otp-gana-encolado", email="pg-otp-gana@demo.com"
    )
    assert await _pedir(client, tienda, TITULAR) == 200
    codigo_titular = await _codigo_actual_en_outbox(owner_engine, tienda, TITULAR)

    estados = await asyncio.gather(
        _pedir(client, tienda, TOPEADO),
        _pedir(client, tienda, OTRA_CASILLA),
        _pedir(client, tienda, NUEVO),
        _pedir(client, tienda, OTRA_CASILLA),
    )

    assert list(estados) == [200] * 4
    # El pedido topeado no guarda nada; los otros tres crean email durable.
    assert await _filas_otp(owner_engine, tienda) == 4
    assert await _filas_emails_otp(owner_engine, tienda) == 4
    codigo_otra_casilla = await _codigo_actual_en_outbox(
        owner_engine, tienda, OTRA_CASILLA
    )
    codigo_nuevo = await _codigo_actual_en_outbox(owner_engine, tienda, NUEVO)

    # Los emails a destinos distintos permanecen válidos. Entre dos pedidos
    # al mismo destino, el guard mantiene despachable solo el OTP más reciente.
    assert await _verifica(client, tienda, codigo_titular)
    assert await _verifica(client, tienda, codigo_nuevo)
    assert await _verifica(client, tienda, codigo_otra_casilla)
