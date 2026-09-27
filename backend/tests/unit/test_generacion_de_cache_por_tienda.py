"""B6-08 (2026-09-19): la generacion por tienda del cache de disponibilidad.

Editar o borrar un servicio cambia la disponibilidad de todos los dias de la
tienda. ``invalidate_store_availability`` sube una generacion por tienda que
entra en la clave de los slots: un solo INCR, sin ``delete`` ni comodines
(bloque Fase 0 de CLAUDE.md). La generacion sigue las mismas reglas que la
version por dia de B7-09: INCR + EXPIRE, y la lectura (GETEX) estira el
vencimiento para que nunca se recicle bajo un slot vivo.

El modulo se importa entero para que los tests fallen por la asercion y no
por un ImportError mientras las funciones nuevas no existen.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from core import availability_cache as cache
from tests.unit.test_version_de_cache_expira import FakeRedisConTtl, RelojRedis

DIA = date(2026, 9, 15)
DIA_LEJANO = date(2026, 12, 30)


async def _consultar(redis: RelojRedis, dia: date, contenido: str) -> str:
    """El recorrido de ``AvailabilityService.get_available_slots``."""
    clave = await cache.resolve_slots_key(
        redis, "tienda", dia, "svc", force_all=False, hide_private_reasons=False
    )
    cacheado = await redis.get(clave)
    if cacheado is not None:
        return cacheado
    await redis.setex(clave, cache.SLOTS_TTL_SECONDS, contenido)
    return contenido


@pytest.mark.asyncio
async def test_invalidar_la_tienda_cambia_la_clave_de_cualquier_dia() -> None:
    redis = RelojRedis()
    assert await _consultar(redis, DIA, "[30min]") == "[30min]"
    assert await _consultar(redis, DIA_LEJANO, "[30min]") == "[30min]"

    await cache.invalidate_store_availability(redis, "tienda")

    assert await _consultar(redis, DIA, "[60min]") == "[60min]"
    assert await _consultar(redis, DIA_LEJANO, "[60min]") == "[60min]"


@pytest.mark.asyncio
async def test_invalidar_la_tienda_no_toca_otras_tiendas() -> None:
    redis = RelojRedis()
    clave_otra = await cache.resolve_slots_key(
        redis, "otra", DIA, "svc", force_all=False, hide_private_reasons=False
    )
    await cache.invalidate_store_availability(redis, "tienda")
    assert clave_otra == await cache.resolve_slots_key(
        redis, "otra", DIA, "svc", force_all=False, hide_private_reasons=False
    )


@pytest.mark.asyncio
async def test_la_invalidacion_por_dia_sigue_funcionando() -> None:
    """Turnos y bloqueos siguen invalidando por (tienda, dia local)."""
    redis = RelojRedis()
    await cache.invalidate_store_availability(redis, "tienda")
    assert await _consultar(redis, DIA, "[libre]") == "[libre]"

    await cache.invalidate_availability(
        redis, "tienda", datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)
    )

    assert await _consultar(redis, DIA, "[ocupado]") == "[ocupado]"


@pytest.mark.asyncio
async def test_la_generacion_no_queda_sin_vencimiento_ni_se_borra_nada() -> None:
    redis = FakeRedisConTtl()
    await redis.setex("availability:vieja", cache.SLOTS_TTL_SECONDS, "[viejo]")

    await cache.invalidate_store_availability(redis, "tienda")

    clave = cache.store_generation_key("tienda")
    assert redis.ttl[clave] == cache.VERSION_TTL_SECONDS
    assert redis.store["availability:vieja"] == "[viejo]"


@pytest.mark.asyncio
async def test_una_generacion_vencida_no_resucita_slots_viejos() -> None:
    """Mismo reloj que el rechazo V-diff de B7-09, sobre la generacion."""
    redis = RelojRedis()
    await cache.invalidate_store_availability(redis, "tienda")  # generacion "1"

    # Consulta justo antes de que la generacion cumpla su TTL.
    redis.ahora = cache.VERSION_TTL_SECONDS - 100
    assert await _consultar(redis, DIA, "[30min]") == "[30min]"

    # Pasa el vencimiento original y se edita el servicio.
    redis.ahora = cache.VERSION_TTL_SECONDS + 10
    await cache.invalidate_store_availability(redis, "tienda")

    redis.ahora = cache.VERSION_TTL_SECONDS + 20
    assert await _consultar(redis, DIA, "[60min]") == "[60min]"


@pytest.mark.asyncio
async def test_leer_la_generacion_le_estira_el_vencimiento() -> None:
    redis = RelojRedis()
    await cache.invalidate_store_availability(redis, "tienda")
    redis.ahora = cache.VERSION_TTL_SECONDS - 1

    await cache.current_store_generation(redis, "tienda")

    redis.ahora = cache.VERSION_TTL_SECONDS + cache.SLOTS_TTL_SECONDS
    assert await cache.current_store_generation(redis, "tienda") == "1"
