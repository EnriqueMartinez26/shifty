"""El borde del horizonte publico se cuenta en dias LOCALES.

2026-09-25, revision de perf/f4-back. El ultimo dia del portal es hoy + 120
dias en hora argentina. Un turno a las 23:30 de ese dia ya cae, en UTC, en el
dia siguiente: igual se muestra y se reserva. El dia local siguiente (+121,
que empieza a las 00:00 ART) no se muestra en la grilla.
"""

from __future__ import annotations

from datetime import time, timedelta

import pytest
from httpx import AsyncClient

from core.utils import BOOKING_HORIZON_DAYS, local_to_utc, today_local
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_staff,
    register_and_login,
)


@pytest.mark.asyncio
async def test_las_23_30_del_ultimo_dia_se_muestran_y_se_reservan(
    client: AsyncClient,
) -> None:
    store, token = await register_and_login(
        client, slug="borde-horizonte", email="borde-horizonte@t.com"
    )
    headers = auth_headers(token)
    servicio = await client.post(
        "/services/",
        headers=headers,
        json={"name": "Corto", "duration_minutes": 20, "price": 1000},
    )
    assert servicio.status_code == 201, servicio.text
    service = servicio.json()["public_id"]
    staff = await create_staff(client, token, service, email="pro-borde@t.com")
    for dia in range(7):
        horario = await client.post(
            f"/staff/{staff}/schedules",
            headers=headers,
            json={"day_of_week": dia, "start_time": "00:00:00", "end_time": "23:59:00"},
        )
        assert horario.status_code == 200, horario.text

    ultimo = today_local() + timedelta(days=BOOKING_HORIZON_DAYS)
    las_23_30 = local_to_utc(ultimo, time(23, 30))
    assert las_23_30.date() > ultimo  # en UTC ya es el dia siguiente

    grilla = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": ultimo.isoformat(),
        },
    )
    assert grilla.status_code == 200, grilla.text
    ultimo_slot = next(
        s
        for s in grilla.json()
        if s["start_time"] == "23:30:00" and s["status"] == "available"
    )
    slot = str(ultimo_slot["starts_at"])
    assert slot.startswith(las_23_30.strftime("%Y-%m-%dT%H:%M")), ultimo_slot

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot,
            "client_name": "Borde",
            "client_phone": "+5491100008888",
            "accepts_terms": True,
            "idempotency_key": "borde-horizonte-1",
        },
    )
    assert reserva.status_code == 201, reserva.text

    siguiente = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": (ultimo + timedelta(days=1)).isoformat(),
        },
    )
    assert siguiente.status_code == 422, siguiente.text
