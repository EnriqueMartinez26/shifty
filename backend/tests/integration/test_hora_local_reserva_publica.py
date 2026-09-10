"""La hora que ve el cliente en la reserva publica es hora argentina.

Regresion (2026-09-10): availability devolvia ``start_time`` como la hora
UTC del slot (``current.time()`` con ``current`` ya convertido a UTC). Un
horario de 20:00 a 23:00 salia como "23:00", "23:15"... y el front lo
mostraba tal cual. Peor: para turnos de 21:00 en adelante el front
recomponia fecha local + hora UTC y el instante caia en el dia anterior.
``starts_at``/``ends_at`` siguen en ISO UTC (son la fuente de verdad);
``start_time``/``end_time`` pasan a ser hora local de Argentina.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment

from core.utils import ARGENTINA_TZ
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


@pytest.mark.asyncio
async def test_los_slots_publicos_muestran_hora_argentina(client: AsyncClient) -> None:
    store, token = await register_and_login(
        client, slug="hora-local", email="hora-local@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = (datetime.now(timezone.utc) + timedelta(days=5)).date()
    horario = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": dia.weekday(),
            "start_time": "20:00:00",
            "end_time": "23:00:00",
        },
    )
    assert horario.status_code == 200, horario.text

    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": dia.isoformat(),
            "force_all": "true",
        },
    )
    assert res.status_code == 200, res.text
    slots = res.json()
    assert slots, "sin slots para un horario de 20 a 23"

    primero = slots[0]
    # Lo que el cliente ve: hora local, no UTC.
    assert primero["start_time"] == "20:00:00", primero
    # La fuente de verdad sigue siendo el instante UTC (23:00Z ese dia).
    inicio = datetime.fromisoformat(primero["starts_at"])
    assert inicio.astimezone(timezone.utc).hour == 23
    assert inicio.astimezone(ARGENTINA_TZ).strftime("%H:%M") == "20:00"

    # Un slot despues de las 21:00 local cae en el dia UTC siguiente: la hora
    # local sigue siendo la del dia elegido.
    tarde = next(s for s in slots if s["start_time"] == "22:00:00")
    inicio_tarde = datetime.fromisoformat(tarde["starts_at"])
    assert inicio_tarde.astimezone(timezone.utc).date() == dia + timedelta(days=1)
    assert inicio_tarde.astimezone(ARGENTINA_TZ).date() == dia
    assert tarde["end_time"] == "22:30:00"


@pytest.mark.asyncio
async def test_reservar_con_el_starts_at_del_slot_cae_en_el_dia_elegido(
    client: AsyncClient,
) -> None:
    # El front debe mandar el starts_at ISO del slot (no recomponer fecha +
    # hora): un turno de 22:00 local queda en el dia elegido.
    store, token = await register_and_login(
        client, slug="hora-noche", email="hora-noche@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = (datetime.now(timezone.utc) + timedelta(days=5)).date()
    await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": dia.weekday(),
            "start_time": "20:00:00",
            "end_time": "23:00:00",
        },
    )
    slots = (
        await client.get(
            "/public/availability",
            params={
                "store_public_id": store,
                "service_id": service,
                "date": dia.isoformat(),
                "force_all": "true",
            },
        )
    ).json()
    slot = next(s for s in slots if s["start_time"] == "22:00:00")

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot["starts_at"],
            "client_name": "Noche",
            "client_phone": "+5491155550099",
            "idempotency_key": "hora-noche-2200",
        },
    )
    assert reserva.status_code == 201, reserva.text
    inicio = datetime.fromisoformat(reserva.json()["starts_at"])
    if inicio.tzinfo is None:  # SQLite devuelve el UTC naive; Postgres con +00:00
        inicio = inicio.replace(tzinfo=timezone.utc)
    assert inicio.astimezone(ARGENTINA_TZ).strftime("%Y-%m-%d %H:%M") == f"{dia} 22:00"


@pytest.mark.asyncio
async def test_la_reserva_publica_respeta_el_buffer_y_congela_el_precio(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    # Antes el camino publico ignoraba buffer_minutes (el panel y la
    # disponibilidad si lo aplican) y no congelaba price_amount.
    store, token = await register_and_login(
        client, slug="buffer-pub", email="buffer-pub@example.com"
    )
    ajuste = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"buffer_minutes": 15}
    )
    assert ajuste.status_code == 200, ajuste.text
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": dia.weekday(),
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    base = dia.replace(hour=13, minute=0, second=0, microsecond=0)

    def reserva(starts_at: datetime, key: str) -> dict[str, str]:
        return {
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": starts_at.isoformat(),
            "client_name": "Buffer",
            "client_phone": "+5491155550077",
            "idempotency_key": key,
        }

    primera = await client.post(
        "/public/appointments", json=reserva(base, "buffer-primera-1")
    )
    assert primera.status_code == 201, primera.text

    # Pegado al anterior (30 min de servicio, 15 de buffer): rechazado.
    pegado = await client.post(
        "/public/appointments",
        json=reserva(base + timedelta(minutes=30), "buffer-pegado-1"),
    )
    assert pegado.status_code == 409, pegado.text

    # Con el buffer respetado: entra.
    separado = await client.post(
        "/public/appointments",
        json=reserva(base + timedelta(minutes=45), "buffer-separado-1"),
    )
    assert separado.status_code == 201, separado.text

    # Precio congelado: cambiar el precio del servicio no toca el turno.
    async def precio_guardado() -> float:
        fila = await test_session.execute(
            select(Appointment.price_amount).where(
                Appointment.idempotency_key == "buffer-primera-1"
            )
        )
        valor = fila.scalar_one()
        assert valor is not None, "la reserva publica no congelo price_amount"
        return float(valor)

    assert await precio_guardado() == 10000.0
    cambio = await client.patch(
        f"/services/{service}", headers=auth_headers(token), json={"price": 99999}
    )
    assert cambio.status_code == 200, cambio.text
    assert await precio_guardado() == 10000.0
