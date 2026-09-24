"""Con el Redis de cache caido, la disponibilidad sale de la base: 200, no 500.

F1-10 (plan de rendimiento, R9-12, 2026-09-24). Sintoma: la lectura del
cache en ``AvailabilityService.get_available_slots`` (GETEX de generacion y
version, GET de la clave, SETEX al final) no atrapaba
``REDIS_UNAVAILABLE_ERRORS``: con Redis caido -o lleno con ``noeviction``,
porque GETEX escribe el TTL- ``/public/availability`` devolvia 500. Un error
de cache ahora es un MISS: se calcula desde la base, no se escribe el cache y
queda un warning por request.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from structlog.testing import capture_logs

from core.redis import get_availability_cache
from main import app
from tests.conftest import MockRedis
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
)


class _CacheCaido(MockRedis):
    def __init__(self, *, falla_en: set[str]) -> None:
        super().__init__()
        self.falla_en = falla_en

    def _quizas_fallar(self, operacion: str) -> None:
        if operacion in self.falla_en:
            raise RedisConnectionError("Error 111 connecting to redis-cache:6379.")

    async def getex(self, key: str, ex: int | None = None) -> str | None:
        self._quizas_fallar("getex")
        return await super().getex(key, ex=ex)

    async def get(self, key: str) -> str | None:
        self._quizas_fallar("get")
        return await super().get(key)

    async def setex(self, key: str, seconds: int, value: object) -> bool:
        self._quizas_fallar("setex")
        return await super().setex(key, seconds, value)


async def _tienda(client: AsyncClient, slug: str) -> tuple[str, str, str]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return store, service, dia.date().isoformat()


async def _disponibilidad(
    client: AsyncClient, store: str, service: str, dia: str
) -> Any:
    return await client.get(
        "/public/availability",
        params={"store_public_id": store, "service_id": service, "date": dia},
    )


def _usar_cache(doble: MockRedis) -> None:
    async def fake() -> MockRedis:
        return doble

    app.dependency_overrides[get_availability_cache] = fake


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "falla_en", [{"getex"}, {"get"}, {"setex"}, {"getex", "get", "setex"}]
)
async def test_un_error_de_cache_es_un_miss_y_da_los_mismos_slots(
    client: AsyncClient, falla_en: set[str]
) -> None:
    store, service, dia = await _tienda(client, "disp-redis-caido")
    sano = await _disponibilidad(client, store, service, dia)
    assert sano.status_code == 200, sano.text
    assert sano.json(), "la tienda de prueba tiene que tener slots"

    caido = _CacheCaido(falla_en=falla_en)
    _usar_cache(caido)
    with capture_logs() as eventos:
        respuesta = await _disponibilidad(client, store, service, dia)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == sano.json()
    avisos = [e for e in eventos if e["event"] == "availability_cache_unavailable"]
    assert len(avisos) == 1, "un solo warning por request"
    assert avisos[0]["error_type"] == "ConnectionError"
    if falla_en & {"getex", "get"}:
        assert caido.store == {}, "con la lectura caida no se escribe el cache"
