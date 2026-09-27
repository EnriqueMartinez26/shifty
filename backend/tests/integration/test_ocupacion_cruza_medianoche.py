"""La ocupacion del dia se carga por solapamiento, no por hora de inicio.

Auditoria 2, AUD2-B1-13 (2026-09-20). Sintoma: `_load_occupancy` cargaba los
bloqueos del dia con un predicado de solapamiento correcto
(`starts_at < day_end AND ends_at > day_start`) pero los turnos por
`starts_at` dentro de la ventana. Un turno que empieza el dia local anterior y
termina dentro del dia consultado no entraba en `booked`, asi que un slot que
lo pisa -o que queda a menos de `buffer_minutes`- se ofrecia como `available`
y el alta despues lo rechazaba con 409.

El hallazgo venia marcado como DUDOSO porque con una tienda normal
(09:00-18:00) no se puede construir. Con un horario que arranca a la
medianoche local si: este test es la evidencia de que el sintoma es real.
Reglas 10 y 12: los rangos se comparan como rangos.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import ARGENTINA_TZ, local_to_utc
from modules.appointments.model import Appointment
from modules.services.model import Service
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _horario(
    client: AsyncClient, token: str, staff: str, dia: datetime, desde: str, hasta: str
) -> None:
    res = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": dia.weekday(),
            "start_time": desde,
            "end_time": hasta,
        },
    )
    assert res.status_code == 200, res.text


async def _estado_del_slot(
    client: AsyncClient, store: str, service: str, staff: str, slot: datetime
) -> str:
    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": slot.astimezone(ARGENTINA_TZ).date().isoformat(),
            "force_all": "true",
        },
    )
    assert res.status_code == 200, res.text
    for s in res.json():
        if s["staff_id"] == staff and datetime.fromisoformat(s["starts_at"]) == slot:
            return str(s["status"])
    raise AssertionError(f"el slot {slot.isoformat()} no aparece en la disponibilidad")


@pytest.mark.asyncio
async def test_un_turno_que_cruza_la_medianoche_tapa_el_slot_del_dia_siguiente(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store_pid, token = await register_and_login(
        client, slug="medianoche", email="medianoche@example.com"
    )
    service_pid = await create_service(client, token)
    staff_pid = await create_staff(client, token, service_pid)

    # Dia local D con horario de trasnoche: 00:00 a 06:00. El dia anterior
    # atiende hasta tarde, que es de donde viene el turno que cruza.
    dia = (datetime.now(timezone.utc) + timedelta(days=5)).astimezone(ARGENTINA_TZ)
    anterior = dia - timedelta(days=1)
    await _horario(client, token, staff_pid, dia, "00:00:00", "06:00:00")
    await _horario(client, token, staff_pid, anterior, "18:00:00", "23:59:00")

    # Turno 23:30-00:30 locales del dia anterior: se escribe directo porque lo
    # que se prueba es la LECTURA de la disponibilidad, no el alta.
    inicio = local_to_utc(
        anterior.date(), datetime.min.time().replace(hour=23, minute=30)
    )
    tienda = (
        await test_session.execute(select(Store).where(Store.public_id == store_pid))
    ).scalar_one()
    servicio = (
        await test_session.execute(
            select(Service).where(Service.public_id == service_pid)
        )
    ).scalar_one()
    test_session.add(
        Appointment(
            store_id=tienda.id,
            service_id=servicio.id,
            staff_id=staff_pid,
            client_name="Trasnoche",
            client_phone="5491155550300",
            starts_at=inicio,
            ends_at=inicio + timedelta(minutes=60),
            duration_minutes=60,
        )
    )
    await test_session.commit()

    primer_slot = local_to_utc(dia.date(), datetime.min.time())

    assert (
        await _estado_del_slot(client, store_pid, service_pid, staff_pid, primer_slot)
        == "booked"
    )
    # El slot siguiente, ya fuera del turno que cruza, sigue disponible.
    assert (
        await _estado_del_slot(
            client,
            store_pid,
            service_pid,
            staff_pid,
            primer_slot + timedelta(minutes=30),
        )
        == "available"
    )


@pytest.mark.asyncio
async def test_el_buffer_del_turno_de_ayer_tambien_tapa_el_primer_slot(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El obstaculo es el turno MAS el buffer, asi que la ventana va ensanchada.

    Un turno que termina justo a la medianoche no solapa con el dia siguiente,
    pero con ``buffer_minutes`` sigue tapando el primer slot. Si la consulta
    usara el solapamiento pelado tampoco lo traeria.
    """
    store_pid, token = await register_and_login(
        client, slug="medianoche-buffer", email="medianoche-buffer@example.com"
    )
    ajuste = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"buffer_minutes": 30}
    )
    assert ajuste.status_code == 200, ajuste.text
    service_pid = await create_service(client, token)
    staff_pid = await create_staff(client, token, service_pid)

    dia = (datetime.now(timezone.utc) + timedelta(days=5)).astimezone(ARGENTINA_TZ)
    anterior = dia - timedelta(days=1)
    await _horario(client, token, staff_pid, dia, "00:00:00", "06:00:00")
    await _horario(client, token, staff_pid, anterior, "18:00:00", "23:59:00")

    # Turno 23:00-00:00 locales: termina exacto a la medianoche.
    inicio = local_to_utc(
        anterior.date(), datetime.min.time().replace(hour=23, minute=0)
    )
    tienda = (
        await test_session.execute(select(Store).where(Store.public_id == store_pid))
    ).scalar_one()
    servicio = (
        await test_session.execute(
            select(Service).where(Service.public_id == service_pid)
        )
    ).scalar_one()
    test_session.add(
        Appointment(
            store_id=tienda.id,
            service_id=servicio.id,
            staff_id=staff_pid,
            client_name="Ultimo de ayer",
            client_phone="5491155550301",
            starts_at=inicio,
            ends_at=inicio + timedelta(minutes=60),
            duration_minutes=60,
        )
    )
    await test_session.commit()

    primer_slot = local_to_utc(dia.date(), datetime.min.time())

    assert (
        await _estado_del_slot(client, store_pid, service_pid, staff_pid, primer_slot)
        == "booked"
    )
