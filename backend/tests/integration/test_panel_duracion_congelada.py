"""El panel mide la duracion del turno con el snapshot del turno, no con el
servicio de hoy.

2026-09-20, hallazgo AUD2-B5-10: ``ReportService._professional_item`` usa
``appointment.duration_minutes`` (el snapshot congelado al reservar), pero
``DashboardRepository.booked_minutes_between`` y ``average_duration_between``
hacian ``SUM/AVG(Service.duration_minutes)``, la duracion de lista de HOY.
Sintoma: el dueno cambia un servicio de 30 a 45 minutos y la ocupacion de hoy
en el panel se recalcula hacia atras, deja de coincidir con el reporte por
profesional del mismo dia y muestra dos numeros para el mismo hecho, sin que
nada haya cambiado en la agenda.

Es el mismo motivo por el que ``price_amount`` se congela en el turno ("el
turno tiene que valer lo que valia cuando se reservo"): la duracion se congela
por la misma razon y el panel la ignoraba.

Reloj congelado: miercoles 2026-09-16 a las 15:00 ART, como el resto del panel.
"""

from datetime import time
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import core.utils
from modules.appointments.model import AppointmentStatus
from modules.services.model import Service
from modules.staff.model import Schedule, Staff
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_panel_en_service import HOY_LOCAL, _RelojCongelado, _turno

# Agenda del dia: 09:00-17:00 = 480 minutos disponibles.
MINUTOS_DISPONIBLES = 480
DURACION_AL_RESERVAR = 30
DURACION_NUEVA = 45


@pytest.mark.asyncio
async def test_cambiar_la_duracion_del_servicio_no_mueve_la_ocupacion_de_ayer(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core.utils, "datetime", _RelojCongelado)
    store_public_id, token = await register_and_login(
        client, slug="aud2b510", email="aud2b510@test.com"
    )
    servicio_public_id = await create_service(client, token)  # 30 minutos
    staff_public_id = await create_staff(
        client, token, servicio_public_id, email="pro-aud2b510@test.com"
    )
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    servicio = (
        await test_session.execute(
            select(Service).where(Service.public_id == servicio_public_id)
        )
    ).scalar_one()
    staff = (
        await test_session.execute(select(Staff).where(Staff.id == staff_public_id))
    ).scalar_one()
    assert servicio.duration_minutes == DURACION_AL_RESERVAR
    cliente = User(
        email="cliente-aud2b510@test.com",
        hashed_password="no-se-loguea",
        first_name="Ana",
        last_name="Cliente",
        role=UserRole.CLIENT,
        store_id=store.id,
    )
    test_session.add_all(
        [
            cliente,
            Schedule(
                staff_id=staff.id,
                store_id=store.id,
                day_of_week=HOY_LOCAL.weekday(),
                start_time=time(9, 0),
                end_time=time(17, 0),
            ),
        ]
    )
    await test_session.commit()

    await _turno(
        test_session,
        store=store,
        cliente=cliente,
        servicio=servicio,
        staff=staff,
        dia=HOY_LOCAL,
        hora=time(16, 0),
        estado=AppointmentStatus.CONFIRMED,
        clave="aud2b510-hoy",
    )

    esperado = round((DURACION_AL_RESERVAR / MINUTOS_DISPONIBLES) * 100, 2)

    async def stats() -> dict[str, float]:
        res = await client.get("/dashboard/summary", headers=auth_headers(token))
        assert res.status_code == 200, res.text
        return dict(res.json()["stats"])

    antes = await stats()
    assert antes["occupancy_rate"] == esperado
    assert antes["average_appointment_minutes"] == DURACION_AL_RESERVAR

    # El dueno alarga el servicio. La agenda de hoy no cambio.
    servicio.duration_minutes = DURACION_NUEVA
    await test_session.commit()
    test_session.expire_all()

    despues = await stats()
    assert despues["occupancy_rate"] == esperado
    assert despues["average_appointment_minutes"] == DURACION_AL_RESERVAR
