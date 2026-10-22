"""Trampa para bots en la reserva publica (paquete antiabuso, S4).

2026-10-22. ``PublicBookingCreate`` suma dos campos OPCIONALES que solo llena
el wizard: ``website`` (un campo oculto que una persona nunca ve, asi que
tiene que llegar vacio) y ``form_elapsed_ms`` (cuanto tardo en llenarse el
formulario). Un ``website`` no vacio, o un ``form_elapsed_ms`` presente y
menor a 2500, es 400 ``BOOKING_REJECTED`` antes de escribir nada y antes de
leer o gastar la cuota diaria por IP. Sin los campos la reserva es la de
siempre (los clientes viejos siguen andando). Ninguno de los dos entra en la
clave de idempotencia.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from modules.appointments.model import Appointment
from modules.users.model import User, UserRole
from tests.integration.test_caracterizacion_alta_publica import _reserva, _tienda
from tests.integration.test_portal_cuota_diaria_por_ip import (
    IP,
    _RedisDeEstado,
    redis_de_estado,  # noqa: F401 (fixture)
)

MENSAJE = "No pudimos registrar la reserva. Probá de nuevo."


async def _contar(session: AsyncSession, modelo: Any, *filtros: Any) -> int:
    session.expire_all()
    consulta = select(func.count()).select_from(modelo)
    if filtros:
        consulta = consulta.where(*filtros)
    return int(await session.scalar(consulta) or 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "trampa",
    [
        {"website": "http://spam.example"},
        {"website": " "},
        {"form_elapsed_ms": 0},
        {"form_elapsed_ms": 2499},
    ],
)
async def test_un_bot_recibe_400_antes_de_escribir_y_sin_gastar_cuota(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    redis_de_estado: _RedisDeEstado,  # noqa: F811
    trampa: dict[str, Any],
) -> None:
    t = await _tienda(client, "trampa-bot")
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)

    res = await client.post(
        "/public/appointments",
        headers={"X-Forwarded-For": IP},
        json=_reserva(t, "trampa-bot-0001", **trampa),
    )

    assert res.status_code == 400, res.text
    assert res.json()["error_code"] == "BOOKING_REJECTED"
    assert res.json()["message"] == MENSAJE
    assert await _contar(test_session, Appointment) == 0
    assert await _contar(test_session, User, User.role == UserRole.CLIENT) == 0
    assert redis_de_estado.de_la_cuota() == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "campos",
    [
        {},
        {"website": ""},
        {"website": None},
        {"form_elapsed_ms": 2500},
        {"website": "", "form_elapsed_ms": 86_400_000},
    ],
)
async def test_una_persona_reserva_con_o_sin_los_campos(
    client: AsyncClient, campos: dict[str, Any]
) -> None:
    t = await _tienda(client, "trampa-persona")

    res = await client.post(
        "/public/appointments", json=_reserva(t, "trampa-persona-01", **campos)
    )

    assert res.status_code == 201, res.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "campos",
    [{"form_elapsed_ms": -1}, {"form_elapsed_ms": 86_400_001}, {"website": "x" * 201}],
)
async def test_los_campos_tienen_cotas(
    client: AsyncClient, test_session: AsyncSession, campos: dict[str, Any]
) -> None:
    t = await _tienda(client, "trampa-cotas")

    res = await client.post(
        "/public/appointments", json=_reserva(t, "trampa-cotas-001", **campos)
    )

    assert res.status_code == 422, res.text
    assert await _contar(test_session, Appointment) == 0


@pytest.mark.asyncio
async def test_los_campos_no_cambian_la_idempotencia(client: AsyncClient) -> None:
    """El reintento de la misma reserva con otro ``form_elapsed_ms`` devuelve
    la misma reserva: con clave explicita y con la clave derivada."""
    t = await _tienda(client, "trampa-idem")
    con_clave = _reserva(t, "trampa-idem-0001", form_elapsed_ms=4000)
    primera = await client.post("/public/appointments", json=con_clave)
    assert primera.status_code == 201, primera.text
    con_clave["form_elapsed_ms"] = 9000
    replay = await client.post("/public/appointments", json=con_clave)
    assert replay.status_code == 201, replay.text
    assert replay.json()["public_id"] == primera.json()["public_id"]

    sin_clave = _reserva(
        t,
        "no-se-usa",
        starts_at=t.slot.replace(hour=15).isoformat(),
        form_elapsed_ms=3000,
    )
    del sin_clave["idempotency_key"]
    derivada = await client.post("/public/appointments", json=sin_clave)
    assert derivada.status_code == 201, derivada.text
    sin_clave["form_elapsed_ms"] = 12000
    sin_clave["website"] = ""
    replay_derivada = await client.post("/public/appointments", json=sin_clave)
    assert replay_derivada.status_code == 201, replay_derivada.text
    assert replay_derivada.json()["public_id"] == derivada.json()["public_id"]
