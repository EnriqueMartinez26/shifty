"""La agenda cacheada no estira la vida de lo que se deriva de ella (F3-02).

Revision independiente de perf/f3a (2026-09-24):

1. Cota de frescura. Los slots derivados de una agenda del nivel 2 que ya
   tenia 299 s recibian un TTL nuevo de 300 s: si una invalidacion se perdia
   (Redis caido al invalidar es fail-open, F1-10), el dato viejo podia
   servirse hasta ~600 s. Ahora la agenda guarda cuando se armo y los slots
   derivados de ella viven lo que le queda a la agenda: la cota vuelve a ser
   ``DAY_AGENDA_TTL_SECONDS`` desde la lectura de la base.
2. Un Redis que falla en CUALQUIER lectura del request (tambien la de la
   agenda) es un MISS con un solo warning y sin escrituras. Antes el fallo
   al leer la agenda dejaba viva la clave de los slots y el request
   escribia (y podia loguear un segundo warning).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from structlog.testing import capture_logs

import core.utils
from core.availability_cache import DAY_AGENDA_TTL_SECONDS
from core.redis import get_availability_cache
from main import app
from tests.conftest import MockRedis
from tests.integration.test_disponibilidad_sentencias import (
    _disponibilidad,
    _local,
    _tienda,
)


class _RedisConTtl(MockRedis):
    def __init__(self) -> None:
        super().__init__()
        self.ttl: dict[str, int] = {}

    async def setex(self, key: str, seconds: int, value: object) -> bool:
        self.ttl[key] = seconds
        return await super().setex(key, seconds, value)


class _AgendaIlegible(MockRedis):
    """Redis que responde todo menos la lectura de la agenda del dia."""

    async def get(self, key: str) -> str | None:
        if key.startswith("availability:agenda:"):
            raise RedisConnectionError("Error 111 connecting to redis-cache:6379.")
        return await super().get(key)


def _usar(doble: MockRedis) -> None:
    async def fake() -> MockRedis:
        return doble

    app.dependency_overrides[get_availability_cache] = fake


def _clave_de_slots(redis: _RedisConTtl, servicio: str) -> str:
    (clave,) = [k for k in redis.ttl if f":{servicio}:" in k]
    return clave


@pytest.mark.asyncio
async def test_los_slots_derivados_viven_lo_que_le_queda_a_la_agenda(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "agenda-ttl")
    redis = _RedisConTtl()
    _usar(redis)
    armado = _local(t.dia, "07:15")

    # La agenda se arma de la base con el primer servicio.
    monkeypatch.setattr(core.utils, "now_utc", lambda: armado)
    await _disponibilidad(client, t, t.servicios[0])
    (agenda,) = [k for k in redis.ttl if k.startswith("availability:agenda:")]
    assert redis.ttl[agenda] == DAY_AGENDA_TTL_SECONDS
    assert redis.ttl[_clave_de_slots(redis, t.servicios[0])] == DAY_AGENDA_TTL_SECONDS

    # 200 s despues, el segundo servicio sale de la agenda cacheada.
    monkeypatch.setattr(core.utils, "now_utc", lambda: armado + timedelta(seconds=200))
    await _disponibilidad(client, t, t.servicios[1])
    assert redis.ttl[_clave_de_slots(redis, t.servicios[1])] == (
        DAY_AGENDA_TTL_SECONDS - 200
    )

    # Con la agenda a punto de vencer, el TTL no baja de 1 s.
    monkeypatch.setattr(
        core.utils, "now_utc", lambda: armado + timedelta(seconds=10_000)
    )
    await _disponibilidad(client, t, t.servicios[2])
    assert redis.ttl[_clave_de_slots(redis, t.servicios[2])] == 1


@pytest.mark.asyncio
async def test_si_falla_la_lectura_de_la_agenda_es_miss_sin_escrituras(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "agenda-caida")
    sano: Any = await _disponibilidad(client, t, t.servicios[0])

    caido = _AgendaIlegible()
    _usar(caido)
    with capture_logs() as eventos:
        respuesta = await _disponibilidad(client, t, t.servicios[0])

    assert respuesta == sano
    avisos = [e for e in eventos if e["event"] == "availability_cache_unavailable"]
    assert len(avisos) == 1, avisos
    assert not [k for k in caido.store if not k.startswith("availability:v:")], (
        "con una lectura caida no se escribe el cache"
    )
