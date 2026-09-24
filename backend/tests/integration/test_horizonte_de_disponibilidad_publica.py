"""La disponibilidad publica solo responde fechas en [hoy - 1, hoy + 120].

F1-11 (plan de rendimiento, R9-01, decision 14 del dueno, 2026-09-24).
Sintoma: ``/public/availability`` aceptaba cualquier fecha, y cada fecha es
una clave de cache distinta (tienda x dia x version x servicio x
``force_all``). Una sola IP dentro del rate limit publico creaba cientos de
claves por minuto y podia llenar el Redis de cache. El horizonte acota la
cardinalidad. Es contrato publico: fuera del rango responde 422.

"Hoy" es el dia local argentino (``core.utils.today_local``): el dia de
negocio, no el UTC.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient

from core.utils import today_local
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    create_service,
    register_and_login,
)


async def _pedir(client: AsyncClient, store: str, service: str, dia: str) -> int:
    res = await client.get(
        "/public/availability",
        params={"store_public_id": store, "service_id": service, "date": dia},
    )
    return res.status_code


@pytest.mark.asyncio
async def test_el_horizonte_de_fechas_es_ayer_a_ciento_veinte_dias(
    client: AsyncClient,
) -> None:
    store, token = await register_and_login(
        client, slug="horizonte-disp", email="horizonte-disp@example.com"
    )
    service = await create_service(client, token)
    hoy = today_local()

    dentro = [hoy - timedelta(days=1), hoy, hoy + timedelta(days=120)]
    fuera = [hoy - timedelta(days=2), hoy + timedelta(days=121)]

    for dia in dentro:
        assert await _pedir(client, store, service, dia.isoformat()) == 200, dia
    for dia in fuera:
        assert await _pedir(client, store, service, dia.isoformat()) == 422, dia


@pytest.mark.asyncio
async def test_una_fecha_lejana_no_toca_el_cache(client: AsyncClient) -> None:
    """El rechazo va antes de la base y del cache: no crea claves."""
    from core.redis import get_availability_cache
    from main import app

    store, token = await register_and_login(
        client, slug="horizonte-cache", email="horizonte-cache@example.com"
    )
    service = await create_service(client, token)
    cache = await app.dependency_overrides[get_availability_cache]()
    antes = dict(cache.store)

    lejos = (today_local() + timedelta(days=3650)).isoformat()
    assert await _pedir(client, store, service, lejos) == 422

    assert cache.store == antes
