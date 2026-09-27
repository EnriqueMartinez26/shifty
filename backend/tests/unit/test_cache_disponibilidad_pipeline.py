"""El cache de disponibilidad habla con Redis en UNA ida y vuelta por paso.

F3-09 (plan de rendimiento, R1-08, 2026-09-24). Sintoma: cada lectura de
disponibilidad hacia dos GETEX en serie (generacion de la tienda y version del
dia) antes del GET de los slots, y cada invalidacion un INCR y un EXPIRE por
dia tocado, todos en serie. Con el Redis del cache en otra maquina cada ida y
vuelta suma latencia al endpoint mas pedido y al commit del alta.

Ahora van en un pipeline. La semantica no cambia (la guarda de CLAUDE.md,
"Disponibilidad"): el GETEX sigue estirando el TTL de las dos claves, se
invalida con INCR + EXPIRE y nunca se borra una clave ni se usan comodines.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest

from core import availability_cache as cache
from tests.redis_pipeline_double import PipelineDouble

UN_TURNO_NOCTURNO = datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc)  # 22:00 del 15
DIA = date(2026, 9, 15)


class _Pipeline(PipelineDouble):
    async def execute(self, raise_on_error: bool = True) -> list[Any]:
        self._owner.idas += 1
        self._owner.en_pipeline = True
        try:
            return await super().execute(raise_on_error)
        finally:
            self._owner.en_pipeline = False


class _RedisQueCuentaIdas:
    """Cuenta idas y vueltas: un comando suelto es una, un pipeline tambien."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int | None] = {}
        self.comandos: list[str] = []
        self.idas = 0
        self.en_pipeline = False

    def _ida(self, comando: str) -> None:
        self.comandos.append(comando)
        if not self.en_pipeline:
            self.idas += 1

    async def get(self, key: str) -> str | None:
        self._ida("get")
        return self.store.get(key)

    async def getex(self, key: str, *, ex: int) -> str | None:
        self._ida("getex")
        if key in self.store:
            self.ttl[key] = ex
        return self.store.get(key)

    async def setex(self, key: str, seconds: int, value: str) -> bool:
        self._ida("setex")
        self.store[key] = value
        self.ttl[key] = seconds
        return True

    async def incr(self, key: str) -> int:
        self._ida("incr")
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        self.ttl.setdefault(key, None)
        return int(self.store[key])

    async def expire(self, key: str, seconds: int) -> bool:
        self._ida("expire")
        if key not in self.store:
            return False
        self.ttl[key] = seconds
        return True

    def pipeline(self, transaction: bool = True) -> _Pipeline:
        return _Pipeline(self)


@pytest.mark.asyncio
async def test_resolver_la_clave_es_una_sola_ida_y_estira_las_dos_claves() -> None:
    redis = _RedisQueCuentaIdas()
    await cache.invalidate_store_availability(redis, "tienda")
    await cache.invalidate_availability(redis, "tienda", UN_TURNO_NOCTURNO)
    redis.idas, redis.ttl = 0, {}

    clave = await cache.resolve_slots_key(
        redis, "tienda", DIA, "svc", force_all=False, hide_private_reasons=True
    )

    assert redis.idas == 1, "generacion y version en un solo pipeline"
    assert ":g1:v1:svc:" in clave, clave
    # El GETEX sigue estirando el vencimiento de las dos (B7-09).
    assert redis.ttl == {
        cache.store_generation_key("tienda"): cache.VERSION_TTL_SECONDS,
        cache.version_key("tienda", DIA): cache.VERSION_TTL_SECONDS,
    }


@pytest.mark.asyncio
async def test_invalidar_varios_dias_es_una_sola_ida_sin_borrar_nada() -> None:
    redis = _RedisQueCuentaIdas()

    # El turno de 22:00 local toca el dia local (15) y el dia UTC (16).
    await cache.invalidate_availability(redis, "tienda", UN_TURNO_NOCTURNO)

    assert redis.idas == 1, "INCR + EXPIRE de todos los dias en un pipeline"
    assert sorted(redis.comandos) == ["expire", "expire", "incr", "incr"]
    assert redis.ttl == {
        cache.version_key("tienda", date(2026, 9, 15)): cache.VERSION_TTL_SECONDS,
        cache.version_key("tienda", date(2026, 9, 16)): cache.VERSION_TTL_SECONDS,
    }


@pytest.mark.asyncio
async def test_invalidar_la_tienda_es_una_sola_ida() -> None:
    redis = _RedisQueCuentaIdas()

    await cache.invalidate_store_availability(redis, "tienda")

    assert redis.idas == 1
    assert redis.comandos == ["incr", "expire"]
    assert redis.ttl == {
        cache.store_generation_key("tienda"): cache.VERSION_TTL_SECONDS
    }
