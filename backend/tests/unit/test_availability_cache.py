"""El cache de disponibilidad se invalida de verdad (2026-09-10).

Antes la clave escrita y la invalidada no coincidian (6 vs 4 segmentos, y un
asterisco literal): ninguna invalidacion surtia efecto y la pagina publica
mostraba el estado viejo hasta cinco minutos. Ahora la clave lleva una
version por (tienda, dia local) y invalidar es incrementarla.
"""

from datetime import date, datetime, timezone

import pytest

from core.availability_cache import (
    current_version,
    invalidate_availability,
    invalidate_availability_range,
    local_days_touched,
    slots_key,
    version_key,
)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def setex(self, key: str, seconds: int, value: str) -> bool:
        self.store[key] = value
        return True

    async def incr(self, key: str) -> int:
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])


@pytest.mark.asyncio
async def test_invalidar_cambia_la_clave_y_lo_cacheado_deja_de_servirse() -> None:
    redis = FakeRedis()
    dia = date(2026, 9, 15)
    v0 = await current_version(redis, "tienda", dia)
    clave_vieja = slots_key(
        "tienda", dia, v0, "svc", force_all=False, hide_private_reasons=False
    )
    await redis.setex(clave_vieja, 300, "[viejo]")

    # Un turno de 10:00 local (13:00Z) del mismo dia.
    await invalidate_availability(
        redis, "tienda", datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)
    )

    v1 = await current_version(redis, "tienda", dia)
    assert v1 != v0
    clave_nueva = slots_key(
        "tienda", dia, v1, "svc", force_all=False, hide_private_reasons=False
    )
    assert clave_nueva != clave_vieja
    assert await redis.get(clave_nueva) is None, "lo viejo no debe servirse"


def test_un_turno_nocturno_toca_el_dia_local_y_el_dia_utc() -> None:
    # 22:00 del 15 en Argentina es 01:00Z del 16: hay que invalidar el 15
    # (dia local, que es el que consulta el cliente) y el 16 por las dudas.
    dias = local_days_touched(datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc))
    assert dias == {date(2026, 9, 15), date(2026, 9, 16)}


@pytest.mark.asyncio
async def test_un_rango_de_bloqueo_invalida_cada_dia_que_cubre() -> None:
    redis = FakeRedis()
    await invalidate_availability_range(
        redis,
        "tienda",
        datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc),
    )
    for d in (14, 15, 16, 17):
        assert redis.store.get(version_key("tienda", date(2026, 9, d))) == "1", d
    assert version_key("tienda", date(2026, 9, 13)) not in redis.store
