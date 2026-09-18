"""Las claves de version del cache de disponibilidad caducan.

2026-09-17 (audit B7-09). Sintoma: `invalidate_availability` incrementaba la
version con `INCR`, y un `INCR` sobre una clave inexistente la crea SIN TTL.
`availability:v:{tienda}:{YYYY-MM-DD}` quedaba en Redis para siempre, una por
tienda y por dia tocado (el local y el UTC): ~2x365xN claves por ano que nunca
se liberan, en la misma instancia que sostiene el rate limit y la idempotencia
de cobros. Con `maxmemory`, ese crecimiento sin cota empuja la eviccion de las
otras dos familias, y perder una clave de idempotencia reabre la ventana de
doble cobro.

La guarda del bloque de Fase 0 de CLAUDE.md no se toca: se sigue invalidando
por INCR de la version por (tienda, dia local), y no se borra ninguna clave a
mano ni se usan comodines. Perder la version por TTL equivale a volver a "0"
(`current_version`). Para que eso sea seguro, leer la version tambien le
estira el TTL (GETEX): todo slot se escribe despues de una lectura, asi que la
version siempre sobrevive a sus slots y nunca se recicla bajo uno vivo. La
primera version de este fix solo renovaba en el INCR y dejaba resucitar slots
viejos (rechazo V-diff 2026-09-18, `test_una_version_vencida_no_resucita_...`).

El modulo se importa entero (`from core import availability_cache as cache`)
para que estos tests fallen por la asercion y no por un ImportError cuando
`VERSION_TTL_SECONDS` todavia no existe.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from core import availability_cache as cache

UN_TURNO = datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)
DIA_LOCAL = date(2026, 9, 15)


class FakeRedisConTtl:
    """Doble que recuerda que TTL quedo en cada clave (None = sin vencimiento)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def getex(self, key: str, *, ex: int) -> str | None:
        if key in self.store:
            self.ttl[key] = ex
        return self.store.get(key)

    async def setex(self, key: str, seconds: int, value: str) -> bool:
        self.store[key] = value
        self.ttl[key] = seconds
        return True

    async def incr(self, key: str) -> int:
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        # Redis crea la clave sin TTL; un INCR sobre una que ya existe tampoco
        # le toca el vencimiento.
        self.ttl.setdefault(key, None)
        return int(self.store[key])

    async def expire(self, key: str, seconds: int) -> bool:
        if key not in self.store:
            return False
        self.ttl[key] = seconds
        return True


@pytest.mark.asyncio
async def test_invalidar_no_deja_ninguna_clave_de_version_sin_vencimiento() -> None:
    """El defecto de B7-09, tal cual: la clave quedaba en Redis para siempre."""
    redis = FakeRedisConTtl()

    await cache.invalidate_availability(redis, "tienda", UN_TURNO)

    assert redis.ttl, "la invalidacion tiene que haber tocado alguna clave"
    sin_ttl = [clave for clave, ttl in redis.ttl.items() if ttl is None]
    assert sin_ttl == [], f"claves de version sin vencimiento: {sin_ttl}"


@pytest.mark.asyncio
async def test_invalidar_un_rango_tampoco_deja_claves_eternas() -> None:
    redis = FakeRedisConTtl()

    await cache.invalidate_availability_range(
        redis,
        "tienda",
        datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 17, 13, 0, tzinfo=timezone.utc),
    )

    assert len(redis.ttl) >= 3, redis.ttl
    assert all(ttl == cache.VERSION_TTL_SECONDS for ttl in redis.ttl.values()), (
        redis.ttl
    )


@pytest.mark.asyncio
async def test_renovar_la_invalidacion_reestira_el_vencimiento() -> None:
    """Un dia que se sigue tocando no vence: el EXPIRE va en cada INCR."""
    redis = FakeRedisConTtl()
    clave = cache.version_key("tienda", DIA_LOCAL)

    await cache.invalidate_availability(redis, "tienda", UN_TURNO)
    redis.ttl[clave] = 5  # como si faltaran cinco segundos para vencer
    await cache.invalidate_availability(redis, "tienda", UN_TURNO)

    assert redis.ttl[clave] == cache.VERSION_TTL_SECONDS


@pytest.mark.asyncio
async def test_la_invalidacion_sigue_siendo_por_version_sin_borrar_nada() -> None:
    """La guarda de Fase 0: nada de `delete` a mano ni comodines."""
    redis = FakeRedisConTtl()
    v0 = await cache.current_version(redis, "tienda", DIA_LOCAL)
    vieja = cache.slots_key(
        "tienda", DIA_LOCAL, v0, "svc", force_all=False, hide_private_reasons=False
    )
    await redis.setex(vieja, cache.SLOTS_TTL_SECONDS, "[viejo]")

    await cache.invalidate_availability(redis, "tienda", UN_TURNO)

    v1 = await cache.current_version(redis, "tienda", DIA_LOCAL)
    assert v1 != v0
    nueva = cache.slots_key(
        "tienda", DIA_LOCAL, v1, "svc", force_all=False, hide_private_reasons=False
    )
    assert await redis.get(nueva) is None, "lo viejo no debe servirse"
    # La clave vieja NO se borro: caduca sola y nadie la vuelve a pedir.
    assert redis.store[vieja] == "[viejo]"


def test_la_version_dura_mucho_mas_que_los_slots() -> None:
    """Margen entre los dos TTL, no la garantia en si.

    Que la version no se recicle bajo un slot vivo lo prueba
    `test_una_version_vencida_no_resucita_slots_viejos`, y depende de que la
    lectura estire la version (GETEX). Esto solo fija que el TTL de la version
    sea ordenes de magnitud mayor que el de los slots.
    """
    assert cache.VERSION_TTL_SECONDS > cache.SLOTS_TTL_SECONDS * 100


class RelojRedis:
    """Redis con reloj propio: las claves vencen de verdad cuando pasa su TTL.

    Reproduce lo que el doble sin reloj no puede: que la clave de version
    desaparezca por TTL y el proximo INCR la recree desde 1.
    """

    def __init__(self) -> None:
        self.ahora = 0.0
        self._datos: dict[str, tuple[str, float | None]] = {}

    def _vivo(self, key: str) -> str | None:
        valor = self._datos.get(key)
        if valor is None:
            return None
        dato, vence = valor
        if vence is not None and vence <= self.ahora:
            del self._datos[key]
            return None
        return dato

    async def get(self, key: str) -> str | None:
        return self._vivo(key)

    async def getex(self, key: str, *, ex: int) -> str | None:
        dato = self._vivo(key)
        if dato is not None:
            self._datos[key] = (dato, self.ahora + ex)
        return dato

    async def setex(self, key: str, seconds: int, value: str) -> bool:
        self._datos[key] = (value, self.ahora + seconds)
        return True

    async def incr(self, key: str) -> int:
        dato = self._vivo(key)
        vence = self._datos[key][1] if dato is not None else None
        nuevo = int(dato or "0") + 1
        self._datos[key] = (str(nuevo), vence)
        return nuevo

    async def expire(self, key: str, seconds: int) -> bool:
        dato = self._vivo(key)
        if dato is None:
            return False
        self._datos[key] = (dato, self.ahora + seconds)
        return True


async def _consultar_disponibilidad(redis: RelojRedis, contenido: str) -> str:
    """El recorrido de `AvailabilityService.get_available_slots`.

    `modules/appointments/availability.py`: lee la version (linea 58), busca
    los slots bajo esa version y, si no estan, los calcula y los escribe con
    `setex` de SLOTS_TTL_SECONDS (lineas 106 y 279). `contenido` es lo que
    "calcularia" la base en ese momento.
    """
    version = await cache.current_version(redis, "tienda", DIA_LOCAL)
    clave = cache.slots_key(
        "tienda", DIA_LOCAL, version, "svc", force_all=False, hide_private_reasons=False
    )
    cacheado = await redis.get(clave)
    if cacheado is not None:
        return cacheado
    await redis.setex(clave, cache.SLOTS_TTL_SECONDS, contenido)
    return contenido


@pytest.mark.asyncio
async def test_una_version_vencida_no_resucita_slots_viejos() -> None:
    """Rechazo V-diff de B7-09 (2026-09-18): la invalidacion no invalidaba.

    Con la version renovada solo en cada INCR, una consulta en los ultimos
    300 s de vida de la version escribia slots que le sobrevivian; al vencer,
    la version volvia a "0", la reserva siguiente la dejaba otra vez en "1" y
    se servian los slots de ANTES de la reserva hasta 300 s.
    """
    redis = RelojRedis()
    await cache.invalidate_availability(redis, "tienda", UN_TURNO)  # version "1"

    # Consulta justo antes de que la version cumpla su TTL.
    redis.ahora = cache.VERSION_TTL_SECONDS - 100
    assert await _consultar_disponibilidad(redis, "[libre]") == "[libre]"

    # Pasa el vencimiento original de la version y llega una reserva.
    redis.ahora = cache.VERSION_TTL_SECONDS + 10
    await cache.invalidate_availability(redis, "tienda", UN_TURNO)

    # La siguiente consulta tiene que recalcular: el slot "[libre]" es de
    # antes de la reserva.
    redis.ahora = cache.VERSION_TTL_SECONDS + 20
    assert await _consultar_disponibilidad(redis, "[ocupado]") == "[ocupado]"


@pytest.mark.asyncio
async def test_leer_la_version_le_estira_el_vencimiento() -> None:
    """Toda escritura de slots viene despues de una lectura que estiro la version."""
    redis = RelojRedis()
    await cache.invalidate_availability(redis, "tienda", UN_TURNO)
    redis.ahora = cache.VERSION_TTL_SECONDS - 1

    await cache.current_version(redis, "tienda", DIA_LOCAL)

    redis.ahora = cache.VERSION_TTL_SECONDS + cache.SLOTS_TTL_SECONDS
    assert await cache.current_version(redis, "tienda", DIA_LOCAL) == "1"
