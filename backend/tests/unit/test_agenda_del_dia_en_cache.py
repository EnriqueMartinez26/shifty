"""La agenda cruda del dia vive bajo la misma generacion + version (F3-02).

El nivel 2 del cache de disponibilidad no agrega ninguna invalidacion: su
clave lleva la generacion de la tienda y la version del dia, las mismas que
la de los slots, asi que cada ``INCR`` que ya existe la deja atras. Estos
tests fijan esa propiedad sobre las claves; la de punta a punta (reservar,
cancelar, bloquear, editar un servicio) esta en
``tests/integration/test_disponibilidad_sentencias.py``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from core import availability_cache as cache
from tests.conftest import MockRedis

DIA = date(2026, 9, 15)
OTRO_DIA = date(2026, 9, 17)
TURNO_DEL_DIA = datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)


async def _claves(redis: MockRedis, dia: date = DIA) -> cache.AvailabilityKeys:
    return await cache.resolve_availability_keys(
        redis, "tienda", dia, "svc", force_all=False, hide_private_reasons=True
    )


@pytest.mark.asyncio
async def test_la_agenda_lleva_la_generacion_y_la_version_de_los_slots() -> None:
    redis = MockRedis()
    await cache.invalidate_store_availability(redis, "tienda")
    await cache.invalidate_availability(redis, "tienda", TURNO_DEL_DIA)

    claves = await _claves(redis)

    assert claves.slots.endswith(":svc:0:1")
    assert ":g1:v1:" in claves.slots
    assert claves.day_agenda == "availability:agenda:tienda:2026-09-15:g1:v1"
    assert not claves.day_agenda.startswith(claves.slots)


@pytest.mark.asyncio
async def test_invalidar_el_dia_deja_atras_la_agenda_de_ese_dia_y_no_la_de_otro() -> (
    None
):
    redis = MockRedis()
    antes, otro_antes = await _claves(redis), await _claves(redis, OTRO_DIA)

    await cache.invalidate_availability(redis, "tienda", TURNO_DEL_DIA)

    despues, otro_despues = await _claves(redis), await _claves(redis, OTRO_DIA)
    assert despues.day_agenda != antes.day_agenda
    assert despues.slots != antes.slots
    assert otro_despues == otro_antes


@pytest.mark.asyncio
async def test_invalidar_la_tienda_deja_atras_la_agenda_de_todos_los_dias() -> None:
    redis = MockRedis()
    antes, otro_antes = await _claves(redis), await _claves(redis, OTRO_DIA)

    await cache.invalidate_store_availability(redis, "tienda")

    despues, otro_despues = await _claves(redis), await _claves(redis, OTRO_DIA)
    assert despues.day_agenda != antes.day_agenda
    assert otro_despues.day_agenda != otro_antes.day_agenda


def test_la_agenda_vence_como_los_slots() -> None:
    assert cache.DAY_AGENDA_TTL_SECONDS == cache.SLOTS_TTL_SECONDS == 300
