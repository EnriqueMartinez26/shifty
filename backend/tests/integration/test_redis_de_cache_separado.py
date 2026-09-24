"""F0-15 (plan de rendimiento): el cache de disponibilidad vive en su propio Redis.

El Redis de cache desaloja (`allkeys-lru`) y el de estado no (`noeviction`).
Si una clave de idempotencia cae en el de cache, un desalojo reabre la puerta a
un cobro duplicado; si el cache cae en el de estado, lo llena y hace fallar las
escrituras de lockout y rate limit. Este test recorre el flujo publico completo
(consultar disponibilidad, reservar, cancelar desde el panel) con los dos Redis
separados y mira donde quedo cada clave.
"""

from collections.abc import Iterator

import pytest
from httpx import AsyncClient

import modules.notifications.tasks as tasks
from core.redis import get_availability_cache, get_redis
from main import app
from tests.conftest import MockRedis
from tests.integration.test_cache_disponibilidad import _estado_del_slot, _tienda
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_mails_al_cliente import Buzon


@pytest.fixture
def dos_redis() -> Iterator[tuple[MockRedis, MockRedis]]:
    estado, cache = MockRedis(), MockRedis()

    async def fake_estado() -> MockRedis:
        return estado

    async def fake_cache() -> MockRedis:
        return cache

    app.dependency_overrides[get_redis] = fake_estado
    app.dependency_overrides[get_availability_cache] = fake_cache
    yield estado, cache
    app.dependency_overrides.pop(get_availability_cache, None)


@pytest.mark.asyncio
async def test_cada_clave_va_a_su_redis(
    client: AsyncClient,
    dos_redis: tuple[MockRedis, MockRedis],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    estado, cache = dos_redis
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff, slot = await _tienda(client, "dos-redis")

    assert await _estado_del_slot(client, store, service, staff, slot) == "available"
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Dos Redis",
            "client_phone": "+5491155550077",
            "idempotency_key": "dos-redis-000001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    assert await _estado_del_slot(client, store, service, staff, slot) == "booked"
    cancel = await client.patch(
        f"/appointments/{reserva.json()['public_id']}/cancel",
        headers=auth_headers(token),
    )
    assert cancel.status_code == 200, cancel.text
    assert await _estado_del_slot(client, store, service, staff, slot) == "available"

    en_cache = set(cache.store)
    en_estado = set(estado.store)
    assert any(k.startswith("availability:v:") for k in en_cache), en_cache
    assert any(k.startswith("availability:") and ":v" in k for k in en_cache)
    assert all(k.startswith("availability:") for k in en_cache), (
        f"el Redis de cache recibio claves que no son de disponibilidad: {en_cache}"
    )
    assert not any(k.startswith("availability:") for k in en_estado), (
        f"el cache de disponibilidad escribio en el Redis de estado: {en_estado}"
    )
    assert any(k.startswith("idempotency:") for k in en_estado), en_estado
