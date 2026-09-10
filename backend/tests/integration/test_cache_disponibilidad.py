"""La disponibilidad publica refleja al instante reservas, cancelaciones y bloqueos.

Regresion (2026-09-10): la invalidacion del cache nunca coincidia con la clave
escrita; con el Redis de tests (que persiste dentro del test) estos casos
mostraban el estado viejo despues de reservar, cancelar o bloquear.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _estado_del_slot(
    client: AsyncClient, store: str, service: str, staff: str, slot: datetime
) -> str:
    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": slot.date().isoformat(),
            "force_all": "true",
        },
    )
    assert res.status_code == 200, res.text
    objetivo = slot.isoformat()
    for s in res.json():
        if s["staff_id"] == staff and datetime.fromisoformat(s["starts_at"]) == slot:
            return str(s["status"])
    raise AssertionError(f"slot {objetivo} no aparece en la disponibilidad")


async def _tienda(
    client: AsyncClient, slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)  # 10:00 local
    return store, token, service, staff, slot


@pytest.mark.asyncio
async def test_reservar_y_cancelar_se_ven_al_instante(client: AsyncClient) -> None:
    store, token, service, staff, slot = await _tienda(client, "cache-rc")
    assert await _estado_del_slot(client, store, service, staff, slot) == "available"

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Cache",
            "client_phone": "+5491155550055",
            "idempotency_key": "cache-reserva-0001",
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


@pytest.mark.asyncio
async def test_bloquear_y_desbloquear_se_ven_al_instante(client: AsyncClient) -> None:
    store, token, service, staff, slot = await _tienda(client, "cache-bl")
    assert await _estado_del_slot(client, store, service, staff, slot) == "available"

    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "ends_at": (slot + timedelta(hours=1)).isoformat(),
            "reason": "Vacaciones",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text
    assert await _estado_del_slot(client, store, service, staff, slot) == "blocked"

    borrado = await client.delete(
        f"/appointment-blocks/{bloqueo.json()['public_id']}",
        headers=auth_headers(token),
    )
    assert borrado.status_code in {200, 204}, borrado.text
    assert await _estado_del_slot(client, store, service, staff, slot) == "available"
