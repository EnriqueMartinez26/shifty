"""Cuota diaria de reservas publicas por IP y tienda (paquete antiabuso, S3).

2026-10-22. Sintoma: el limite por minuto (``public:booking:create``) frena
una rafaga pero no a quien reserva de a poco todo el dia desde la misma
conexion, rotando telefonos. Ahora cada IP tiene a lo sumo 10 reservas
publicas EXITOSAS por tienda y por dia (cubetas fijas de 24 h alineadas a
UTC), con ``core/rate_limit.subject_quota_allows`` y la politica
``public-write`` (falla cerrada con Redis caido). La cuota se LEE antes de
escribir y se CONSUME solo despues de una reserva hecha: un 409 o un 422 no
gastan cupo. Pasado el tope es 429 ``BOOKING_DAILY_LIMIT``. La IP no se guarda
en ningun lado: el limitador la hashea en la clave.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient, Response
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import core.rate_limit as rate_limit
import modules.public_api.service as public_service
from core.config import settings
from modules.appointments.model import Appointment
from tests.integration.test_caracterizacion_alta_publica import (
    _reserva,
    _Tienda,
    _tienda,
)
from tests.integration.test_portal_tope_por_telefono import _otra_tienda

IP = "203.0.113.7"
OTRA_IP = "203.0.113.8"
ACCION = "public:booking:daily-per-ip-store"
MENSAJE = (
    "Alcanzaste el límite de reservas por hoy. Si necesitás otra, "
    "escribile a la tienda."
)


class _RedisDeEstado:
    """INCR/EXPIRE/GET en memoria, con las claves a la vista."""

    def __init__(self) -> None:
        self.valores: dict[str, int] = {}
        self.get_falla = False

    def pipeline(self, transaction: bool = True) -> "_Pipeline":
        return _Pipeline(self)

    async def get(self, key: str) -> str | None:
        if self.get_falla:
            raise RedisConnectionError("redis caido")
        valor = self.valores.get(key)
        return None if valor is None else str(valor)

    def de_la_cuota(self) -> dict[str, int]:
        return {k: v for k, v in self.valores.items() if ACCION in k}


class _Pipeline:
    def __init__(self, redis: _RedisDeEstado) -> None:
        self.redis = redis
        self.ops: list[tuple[str, str]] = []

    def incr(self, key: str) -> None:
        self.ops.append(("incr", key))

    def expire(self, key: str, seconds: int) -> None:
        self.ops.append(("expire", key))

    async def execute(self) -> list[Any]:
        resultados: list[Any] = []
        for op, key in self.ops:
            if op == "incr":
                self.redis.valores[key] = self.redis.valores.get(key, 0) + 1
                resultados.append(self.redis.valores[key])
            else:
                resultados.append(True)
        return resultados


@pytest.fixture
def redis_de_estado(monkeypatch: pytest.MonkeyPatch) -> _RedisDeEstado:
    redis = _RedisDeEstado()

    async def fake_get_redis() -> _RedisDeEstado:
        return redis

    monkeypatch.setattr(rate_limit, "get_redis", fake_get_redis)
    return redis


def _con_limites(monkeypatch: pytest.MonkeyPatch) -> None:
    # Despues del alta de las tiendas: el login no gasta cuotas del test.
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)


def _cuerpo(t: _Tienda, i: int, ip: str, **extra: Any) -> dict[str, Any]:
    """Telefono propio (el tope por telefono no interviene), sin email (cada
    telefono nuevo con el mismo email seria 409) y un slot de 30 minutos
    propio desde las 09:00 UTC (la jornada de la tienda va de 09 a 21 UTC)."""
    inicio = t.slot.replace(hour=9) + timedelta(minutes=30 * i)
    cuerpo = _reserva(
        t,
        f"cuota-{ip}-{i:04d}",
        client_phone=f"+54911666{i:05d}",
        client_email=None,
        starts_at=inicio.isoformat(),
    )
    cuerpo.update(extra)
    return cuerpo


async def _reservar(client: AsyncClient, cuerpo: dict[str, Any], ip: str) -> Response:
    return await client.post(
        "/public/appointments", headers={"X-Forwarded-For": ip}, json=cuerpo
    )


async def _turnos(session: AsyncSession) -> int:
    session.expire_all()
    return int(await session.scalar(select(func.count()).select_from(Appointment)) or 0)


@pytest.mark.asyncio
async def test_la_onceava_reserva_del_dia_desde_la_misma_ip_es_429(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    redis_de_estado: _RedisDeEstado,
) -> None:
    t = await _tienda(client, "cuota-ip")
    _con_limites(monkeypatch)
    for i in range(10):
        res = await _reservar(client, _cuerpo(t, i, IP), IP)
        assert res.status_code == 201, (i, res.text)

    onceava = await _reservar(client, _cuerpo(t, 10, IP), IP)

    assert onceava.status_code == 429, onceava.text
    assert onceava.json()["error_code"] == "BOOKING_DAILY_LIMIT"
    assert onceava.json()["message"] == MENSAJE
    assert int(onceava.headers["Retry-After"]) > 0
    assert await _turnos(test_session) == 10
    # Una sola cubeta con las 10 exitosas; la IP no aparece en la clave.
    assert list(redis_de_estado.de_la_cuota().values()) == [10]
    assert all(IP not in clave for clave in redis_de_estado.valores)

    # Otra IP en la misma tienda sigue reservando.
    otra = await _reservar(client, _cuerpo(t, 11, OTRA_IP), OTRA_IP)
    assert otra.status_code == 201, otra.text


@pytest.mark.asyncio
async def test_la_cuota_es_por_tienda_y_el_replay_no_la_mira(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    redis_de_estado: _RedisDeEstado,
) -> None:
    t = await _tienda(client, "cuota-ip-a")
    otra_tienda = await _otra_tienda(client, t, "cuota-ip-b")
    _con_limites(monkeypatch)
    monkeypatch.setattr(public_service, "PUBLIC_BOOKINGS_PER_IP_PER_STORE_PER_DAY", 2)
    primera = _cuerpo(t, 0, IP)
    hecha = await _reservar(client, primera, IP)
    assert hecha.status_code == 201, hecha.text
    assert (await _reservar(client, _cuerpo(t, 1, IP), IP)).status_code == 201
    assert (await _reservar(client, _cuerpo(t, 2, IP), IP)).status_code == 429

    # El reintento de una reserva ya hecha devuelve la misma, sin 429.
    replay = await _reservar(client, primera, IP)
    assert replay.status_code == 201, replay.text
    assert replay.json()["public_id"] == hecha.json()["public_id"]

    # Otra clave: el unico de ``appointments.idempotency_key`` es global.
    en_otra = await _reservar(
        client,
        _cuerpo(otra_tienda, 0, IP, idempotency_key="cuota-otra-tienda-0000"),
        IP,
    )
    assert en_otra.status_code == 201, en_otra.text


@pytest.mark.asyncio
async def test_una_reserva_rechazada_no_gasta_cupo(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    redis_de_estado: _RedisDeEstado,
) -> None:
    t = await _tienda(client, "cuota-ip-rechazo")
    _con_limites(monkeypatch)
    monkeypatch.setattr(public_service, "PUBLIC_BOOKINGS_PER_IP_PER_STORE_PER_DAY", 2)
    assert (await _reservar(client, _cuerpo(t, 0, IP), IP)).status_code == 201
    # El mismo slot con otro telefono: 409 de choque, no consume.
    for i in range(3):
        choque = await _reservar(
            client,
            _cuerpo(
                t,
                0,
                IP,
                client_phone=f"+54911777{i:05d}",
                idempotency_key=f"cuota-choque-{i:04d}",
            ),
            IP,
        )
        assert choque.status_code == 409, choque.text
    assert list(redis_de_estado.de_la_cuota().values()) == [1]

    segunda = await _reservar(client, _cuerpo(t, 1, IP), IP)
    assert segunda.status_code == 201, segunda.text


@pytest.mark.asyncio
async def test_redis_caido_falla_cerrado_antes_de_escribir(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    redis_de_estado: _RedisDeEstado,
) -> None:
    t = await _tienda(client, "cuota-ip-caido")
    _con_limites(monkeypatch)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", True)
    redis_de_estado.get_falla = True

    res = await _reservar(client, _cuerpo(t, 0, IP), IP)

    assert res.status_code == 503, res.text
    assert res.json()["error_code"] == "RATE_LIMIT_UNAVAILABLE"
    assert await _turnos(test_session) == 0
