"""AUD2-B5-10, por el camino real: el dueno alarga el servicio desde la API.

Complemento de ``test_panel_duracion_congelada.py``. Aquel prueba la misma
propiedad mutando ``Service.duration_minutes`` en la sesion del ORM, o sea
verifica la CONSULTA. Este la prueba como la ejerce el dueno: un
``PATCH /services/{public_id}``. Si manana la edicion del servicio tocara algo
mas (una reescritura de los turnos futuros, por ejemplo), el de la sesion
seguiria verde y este se pondria rojo.

Sintoma que cubre: el dueno cambia un servicio de 30 a 60 minutos y, sin tocar
la agenda, la ocupacion de dias YA CERRADOS y la duracion promedio se
duplican. Los numeros del panel dejaban de ser reproducibles: el mismo dia
cerrado daba distinto segun cuando se lo mirara.

``booked_minutes_between`` y ``average_duration_between`` sumaban y promediaban
``Service.duration_minutes`` con un join a ``services``, cuando el turno tiene
su propia columna ``duration_minutes`` congelada al reservar, igual que
``price_amount``. El precio ya habia aprendido esta leccion en
``accredited_revenue_between``; la duracion quedo atras. (Desde F3-04 esas
tres consultas viven en ``DashboardRepository.day_counters`` y
``week_totals``, que suman y promedian el snapshot del turno.)

No hace falta ``coalesce`` contra el catalogo: ``appointments.duration_minutes``
nace NOT NULL (con ``server_default='30'``) en la migracion
``d5ec116d06a3_refactor_backend_v2``, asi que no existe el turno viejo sin
snapshot de duracion. (La columna homonima de ``services`` es otra: esa si
viene del esquema inicial ``91d14f2a04fd``.)

Reloj congelado: "ahora" es el miercoles 2026-09-16 a las 15:00 ART.
"""

from datetime import time, timedelta
from decimal import Decimal
from typing import Any, cast

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

# Distintos de los del test hermano: las dos tiendas conviven en la misma base.
SLUG = "aud2b510api"
EMAIL = "aud2b510api@test.com"


async def _panel(client: AsyncClient, token: str) -> dict[str, Any]:
    res = await client.get("/dashboard/summary", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    return cast(dict[str, Any], res.json()["stats"])


@pytest.mark.asyncio
async def test_alargar_un_servicio_por_la_api_no_cambia_la_ocupacion_ya_medida(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core.utils, "datetime", _RelojCongelado)
    store_public_id, token = await register_and_login(client, slug=SLUG, email=EMAIL)
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    admin = (
        await test_session.execute(select(User).where(User.email == EMAIL))
    ).scalar_one()

    alta = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": "Corte", "duration_minutes": 30, "price": 1000},
    )
    assert alta.status_code == 201, alta.text
    servicio_public_id = cast(str, alta.json()["public_id"])
    servicio = (
        await test_session.execute(
            select(Service).where(Service.public_id == servicio_public_id)
        )
    ).scalar_one()

    profesional = Staff(
        store_id=store.id, first_name="Ac", last_name="Tivo", display_name="Activo"
    )
    test_session.add(profesional)
    await test_session.flush()
    test_session.add(
        Schedule(
            staff_id=profesional.id,
            store_id=store.id,
            day_of_week=HOY_LOCAL.weekday(),
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
    )
    for indice, hora in enumerate((time(10, 0), time(11, 0))):
        starts_at = local_to_utc(HOY_LOCAL, hora)
        test_session.add(
            Appointment(
                service_id=servicio.id,
                staff_id=profesional.id,
                store_id=store.id,
                client_id=admin.id,
                client_name="Cliente",
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=30),
                # Congelada al reservar, como price_amount.
                duration_minutes=30,
                price_amount=Decimal("1000"),
                status=AppointmentStatus.CONFIRMED.value,
                idempotency_key=f"{SLUG}-{indice}",
            )
        )
    await test_session.commit()

    antes = await _panel(client, token)
    # 2 turnos x 30' sobre los 480' de agenda del dia.
    assert antes["occupancy_rate"] == 12.5
    assert antes["average_appointment_minutes"] == 30

    # El camino real del dueno: edita el servicio desde el panel.
    cambio = await client.patch(
        f"/services/{servicio_public_id}",
        headers=auth_headers(token),
        json={"duration_minutes": 60},
    )
    assert cambio.status_code == 200, cambio.text
    assert cambio.json()["duration_minutes"] == 60

    despues = await _panel(client, token)
    # Con el defecto: 25.0 y 60. Los turnos ya reservados siguen durando 30'.
    assert despues["occupancy_rate"] == antes["occupancy_rate"]
    assert (
        despues["average_appointment_minutes"] == antes["average_appointment_minutes"]
    )
