"""La tendencia mensual agrupa por mes argentino, contra Postgres real (S-05).

2026-09-18, seguimiento S-05: ``get_trend`` agrupaba con
``date_trunc('month', starts_at)``, que en Postgres trunca en la zona de la
SESION (UTC en el despliegue), y acotaba con medianoche UTC. Un turno del 31 a
las 22:30 ART (01:30Z del dia 1) caia en el mes siguiente. Ahora la clave del
mes sale de un ``CASE`` sobre los limites ``local_day_start`` de cada mes: el
mismo SQL que ejercita la suite en SQLite
(``tests/integration/test_tendencia_mes_local.py``). Este test confirma que
esa sentencia corre en Postgres (timestamptz contra instantes aware, GROUP BY
sobre la subconsulta) y da los mismos buckets, con el rol de la app y RLS.
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
from tests.integration.test_panel_en_service import _RelojCongelado
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

TURNOS = (
    # 31/07 22:30 ART = 01/08 01:30Z: julio, fuera de la ventana de 2 meses.
    (date(2026, 7, 31), time(22, 30), AppointmentStatus.COMPLETED),
    # 31/08 22:30 ART = 01/09 01:30Z: agosto.
    (date(2026, 8, 31), time(22, 30), AppointmentStatus.COMPLETED),
    # 01/09 00:30 ART = 01/09 03:30Z: septiembre.
    (date(2026, 9, 1), time(0, 30), AppointmentStatus.CANCELLED),
    # 30/09 22:30 ART = 01/10 01:30Z: sigue siendo el mes en curso.
    (date(2026, 9, 30), time(22, 30), AppointmentStatus.PENDING),
)


@pytest.mark.asyncio
async def test_el_turno_del_31_a_las_2230_cuenta_en_su_mes_en_postgres(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core.utils, "datetime", _RelojCongelado)
    store, token = await register_and_login(
        client, app_sessions, slug="pg-s05-tendencia", email="pg-s05@demo.com"
    )
    service_public_id = await create_service(client, token)
    staff_id = await create_staff(
        client, token, service_public_id, email="pro-pg-s05@demo.com"
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
                    select(User).where(User.email == "pg-s05@demo.com")
                )
            ).scalar_one()
            for dia, hora, estado in TURNOS:
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
                        status=estado.value,
                        idempotency_key=f"pg-s05-{dia.isoformat()}",
                    )
                )
            await session.commit()
        finally:
            set_tenant_context(None, False)

    res = await client.get(
        "/reports/trend", params={"months": 2}, headers=auth_headers(token)
    )
    assert res.status_code == 200, res.text
    assert res.json()["points"] == [
        {
            "month": "2026-08",
            "total_appointments": 1,
            "completed_appointments": 1,
            "cancelled_appointments": 0,
        },
        {
            "month": "2026-09",
            "total_appointments": 2,
            "completed_appointments": 0,
            "cancelled_appointments": 1,
        },
    ]
