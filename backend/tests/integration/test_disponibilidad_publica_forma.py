"""La forma del JSON de ``GET /public/availability`` es la del ``TypedDict``.

Audit X-03 (2026-09-18). ``public_api/schemas.py`` tenia un
``AvailabilitySlot`` de Pydantic que ningun endpoint usaba y que solo
declaraba 5 de los 8 campos que el endpoint devuelve (le faltaban
``start_time``, ``end_time`` y ``reason``). Usarlo como ``response_model``
habria recortado el JSON: el front usa ``start_time`` como clave de cada slot
(``BookingStepDateTime.tsx``). Se borro; la forma real es
``modules.appointments.availability.AvailabilitySlot`` y este test la fija.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from modules.appointments.availability import AvailabilitySlot
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
)


@pytest.mark.asyncio
async def test_cada_slot_publico_trae_exactamente_los_campos_del_typeddict(
    client: AsyncClient,
) -> None:
    store, token = await register_and_login(
        client, slug="forma-slots", email="forma-slots@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)

    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": dia.date().isoformat(),
            "force_all": "true",
        },
    )

    assert res.status_code == 200, res.text
    slots = res.json()
    assert slots, "la tienda de prueba deberia tener slots ese dia"
    esperado = set(AvailabilitySlot.__annotations__)
    assert {"start_time", "end_time", "reason"} <= esperado
    assert all(set(slot) == esperado for slot in slots), slots[0]
