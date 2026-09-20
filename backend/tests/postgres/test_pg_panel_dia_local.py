"""El corte de dia del panel es el dia argentino, contra Postgres de verdad.

QUE PRUEBA: que ``GET /dashboard/summary`` cuenta como "hoy" el turno de las
22:30 ART del 16/09 —que se persiste a las 01:30Z del 17— con el reloj
congelado al 16/09 15:00 ART. Es el caso que distingue "dia argentino" de "dia
UTC", y aca recorre el tipo posta (``timestamptz``), el driver posta (asyncpg)
y RLS, que es lo que SQLite no tiene. Eso es todo lo que afirma.

QUE NO PRUEBA, y queda escrito para que nadie lo lea de mas: este test NO
ejercita el defecto naive/aware de AUD2-B5-07. Tenia un
``SET TIME ZONE 'America/Argentina/Buenos_Aires'`` que sugeria lo contrario y
se saco, por dos razones independientes:

1. Un ``SET TIME ZONE`` de sesion no cambia como asyncpg codifica un datetime
   naive contra ``timestamptz``: el driver hace ``obj.astimezone(utc)``, que
   resuelve la zona en el proceso de PYTHON, no en la sesion de la base.
2. Iba en la sesion de la SEMILLA, no en la del request, asi que ni siquiera
   alcanzaba a la consulta del panel.

Un test que finge cubrir algo es peor que no tenerlo (CLAUDE.md §4). La
evidencia real del defecto es ``tests/unit/test_panel_instantes_aware.py``, que
exige que el parametro que se le pasa a la base viaje aware y que el
repositorio no vuelva a descartar la zona. Reproducir el sintoma end-to-end
exigiria fijar la TZ del PROCESO de Python antes de que arranque el interprete
(la variable ``TZ`` del contenedor); ``time.tzset()`` no sirve porque no existe
en Windows.
"""

from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import core.utils
from core.database import _apply_tenant_context, set_tenant_context
from core.utils import local_to_utc
from modules.appointments.model import Appointment, AppointmentStatus
from modules.services.model import Service
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    create_service,
    create_staff,
)
from tests.integration.test_panel_en_service import HOY_LOCAL, _RelojCongelado
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

# (dia local, hora local, cuenta como turno de hoy)
TURNOS = (
    (HOY_LOCAL, time(22, 30), True),  # 01:30Z del 17: sigue siendo hoy en ART
    (HOY_LOCAL, time(10, 0), True),
    (HOY_LOCAL + timedelta(days=1), time(10, 0), False),
)


@pytest.mark.asyncio
async def test_el_turno_de_las_2230_cuenta_en_el_dia_argentino_en_postgres(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core.utils, "datetime", _RelojCongelado)
    store, token = await register_and_login(
        client, app_sessions, slug="pg-b507-panel", email="pg-b507@demo.com"
    )
    service_public_id = await create_service(client, token)
    staff_id = await create_staff(
        client, token, service_public_id, email="pro-pg-b507@demo.com"
    )

    async with app_sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            servicio = (
                await session.execute(
                    select(Service).where(Service.public_id == service_public_id)
                )
            ).scalar_one()
            admin = (
                await session.execute(
                    select(User).where(User.email == "pg-b507@demo.com")
                )
            ).scalar_one()
            for dia, hora, _cuenta in TURNOS:
                starts_at = local_to_utc(dia, hora)
                session.add(
                    Appointment(
                        service_id=servicio.id,
                        staff_id=staff_id,
                        store_id=store,
                        client_id=admin.id,
                        client_name="Cliente",
                        starts_at=starts_at,
                        ends_at=starts_at + timedelta(minutes=30),
                        duration_minutes=30,
                        price_amount=Decimal("10000"),
                        status=AppointmentStatus.CONFIRMED.value,
                        idempotency_key=f"pg-b507-{dia.isoformat()}-{hora.hour}",
                    )
                )
            await session.commit()
        finally:
            set_tenant_context(None, False)

    res = await client.get("/dashboard/summary", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    esperados = sum(1 for _dia, _hora, cuenta in TURNOS if cuenta)
    assert res.json()["stats"]["appointments_today"] == esperados


def test_el_dia_de_la_semilla_es_el_que_congela_el_reloj() -> None:
    """Guarda de la semilla: si HOY_LOCAL cambia, el caso de las 22:30 tambien."""
    assert HOY_LOCAL == date(2026, 9, 16)
