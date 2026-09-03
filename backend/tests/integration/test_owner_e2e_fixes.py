"""Regresiones detectadas en el E2E exhaustivo como dueno de tienda.

1. GET /appointments/search devolvia completed_at/cancelled_at siempre null,
   aunque la entidad los tenia seteados (el GET individual si los mostraba).
2. PATCH /stores/me aceptaba primary_color con formato invalido (no-hex).
"""

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


@pytest.mark.asyncio
async def test_search_expone_completed_at(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="search-ts", email="search-ts@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)

    slot = dia.replace(hour=10, minute=0, second=0, microsecond=0)
    alta = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "idempotency_key": "search-ts-1",
        },
    )
    assert alta.status_code == 201, alta.text
    appt = cast(str, alta.json()["public_id"])

    await client.patch(f"/appointments/{appt}/confirm", headers=auth_headers(token))
    done = await client.patch(
        f"/appointments/{appt}/complete", headers=auth_headers(token)
    )
    assert done.status_code == 200, done.text
    assert done.json()["completed_at"] is not None

    # El mismo turno via /search DEBE traer completed_at poblado (no null).
    fecha = dia.date().isoformat()
    res = await client.get(
        f"/appointments/search?from_date={fecha}&to_date={fecha}&page=1&page_size=20",
        headers=auth_headers(token),
    )
    assert res.status_code == 200, res.text
    items = res.json()["results"]
    match = next(item for item in items if item["public_id"] == appt)
    assert match["completed_at"] is not None, "search no propago completed_at"


@pytest.mark.asyncio
async def test_primary_color_rechaza_no_hex(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="color-val", email="color-val@example.com"
    )
    malo = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"primary_color": "noesuncolor"},
    )
    assert malo.status_code == 422, malo.text

    bueno = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"primary_color": "#3366ff"},
    )
    assert bueno.status_code == 200, bueno.text
    assert bueno.json()["primary_color"] == "#3366ff"
