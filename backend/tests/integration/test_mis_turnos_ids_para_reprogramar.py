"""FF-06 (2026-10-01): "Mis turnos" no traia con que pedir la grilla para reprogramar.

Sintoma: ``GET /public/client/{tienda}/{telefono}/appointments`` devolvia el
nombre del servicio y del profesional, pero no sus ids. El portal no podia
pedir ``/public/availability`` para el turno a reprogramar (la grilla se pide
por ``service_id`` y ``staff_id``) y reprogramaba con un selector de fecha y
hora libre. Ahora cada turno trae ``service_id`` (el ``public_id`` del
servicio) y ``staff_id`` (el id publico del profesional, el mismo que usa la
reserva publica), de forma aditiva (D-20260930-06).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from tests.integration.test_caracterizacion_autogestion import TELEFONO, _con_turno


@pytest.mark.asyncio
async def test_mis_turnos_trae_los_ids_publicos_de_servicio_y_profesional(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno_id = await _con_turno(client, monkeypatch, "ff06-ids")
    turno = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == turno_id)
        )
    ).scalar_one()
    # El id publico del servicio no es su clave interna: sin esta diferencia
    # el test no distinguiria cual de los dos expone la respuesta.
    assert turno.service_id != t.service

    res = await client.get(f"/public/client/{t.store}/{TELEFONO}/appointments")

    assert res.status_code == 200, res.text
    [item] = res.json()["appointments"]
    assert item["public_id"] == turno_id
    assert item["service_id"] == t.service
    assert item["staff_id"] == t.staff
    # Son los mismos ids que usa la grilla de disponibilidad del portal: se
    # pide por ``service_id`` y cada cupo trae el ``staff_id`` del profesional.
    grilla = await client.get(
        "/public/availability",
        params={
            "store_public_id": t.store,
            "service_id": item["service_id"],
            "date": t.slot.date().isoformat(),
        },
    )
    assert grilla.status_code == 200, grilla.text
    assert any(cupo["staff_id"] == item["staff_id"] for cupo in grilla.json())
