"""La ocupacion del panel mide contra la agenda del staff ACTIVO.

2026-09-18, hallazgo B5-11: el comentario prometia "Schedules de staff activo"
pero la consulta sumaba los ``Schedule`` del dia de TODOS los profesionales,
sin join a ``Staff`` ni filtro ``is_active``. Al dar de baja a un profesional
sus horarios quedan cargados, ``total_avail_mins`` seguia contando sus horas y
``occupancy_rate`` quedaba diluido: con un profesional activo de 8 horas, otro
dado de baja de 8 horas y una hora reservada, el panel mostraba 6.25% en vez
de 12.5%. El reporte por profesional ya filtraba por ``Staff.is_active``.

Reloj congelado: "ahora" es el miercoles 2026-09-16 a las 15:00 ART.
"""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import core.utils
from core.utils import local_to_utc
from modules.appointments.model import Appointment, AppointmentStatus
from modules.services.model import Service
from modules.staff.model import Schedule, Staff
from modules.stores.model import Store
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.integration.test_panel_en_service import HOY_LOCAL, _RelojCongelado


@pytest.mark.asyncio
async def test_la_agenda_de_un_profesional_dado_de_baja_no_diluye_la_ocupacion(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core.utils, "datetime", _RelojCongelado)
    store_public_id, token = await register_and_login(
        client, slug="b511-panel", email="b511@test.com"
    )
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    admin = (
        await test_session.execute(select(User).where(User.email == "b511@test.com"))
    ).scalar_one()
    servicio = Service(
        store_id=store.id, name="Hora", duration_minutes=60, price=Decimal("1000")
    )
    activo = Staff(
        store_id=store.id, first_name="Ac", last_name="Tivo", display_name="Activo"
    )
    de_baja = Staff(
        store_id=store.id,
        first_name="De",
        last_name="Baja",
        display_name="De baja",
        is_active=False,
    )
    test_session.add_all([servicio, activo, de_baja])
    await test_session.flush()
    for profesional in (activo, de_baja):
        test_session.add(
            Schedule(
                staff_id=profesional.id,
                store_id=store.id,
                day_of_week=HOY_LOCAL.weekday(),
                start_time=time(9, 0),
                end_time=time(17, 0),
            )
        )
    starts_at = local_to_utc(HOY_LOCAL, time(16, 0))
    test_session.add(
        Appointment(
            service_id=servicio.id,
            staff_id=activo.id,
            store_id=store.id,
            client_id=admin.id,
            client_name="Cliente",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=60),
            duration_minutes=60,
            price_amount=Decimal("1000"),
            status=AppointmentStatus.CONFIRMED.value,
            idempotency_key="b511-hoy",
        )
    )
    await test_session.commit()

    res = await client.get("/dashboard/summary", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    # 60 reservados sobre los 480 del unico profesional activo. Con el
    # defecto: 60 / (480 + 480) = 6.25.
    assert res.json()["stats"]["occupancy_rate"] == 12.5
