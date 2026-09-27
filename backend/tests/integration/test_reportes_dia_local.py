"""El rango del reporte (from_date/to_date) son dias argentinos, no UTC.

2026-09-17, hallazgo B5-05: ``ReportService._range_bounds`` armaba el rango
con ``datetime.combine(from_date, time.min)`` naive, es decir medianoche UTC =
21:00 hora argentina del dia anterior. El dueno pedia el reporte del 15/09 y el
rango real era 14/09 21:00 -> 15/09 21:00 ART: los turnos de la noche del 15
caian en el reporte del 16 y el export CSV/PDF que firma esa fecha no cuadraba
con la caja del dia. Regla 24 de CLAUDE.md: "un dia" de negocio es aritmetica
de calendario con zona (``core.utils.local_to_utc``).

No hace falta congelar el reloj: las fechas van explicitas en la query.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import ARGENTINA_TZ, local_to_utc
from modules.appointments.model import Appointment
from modules.services.model import Service
from modules.staff.model import Staff
from modules.stores.model import Store
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


def _dia_local_futuro() -> date:
    """Un dia local a cuatro dias vista (los bloqueos exigen fecha futura)."""
    return (
        (datetime.now(timezone.utc) + timedelta(days=4)).astimezone(ARGENTINA_TZ).date()
    )


@pytest.mark.asyncio
async def test_el_turno_de_las_2230_cae_en_el_reporte_de_su_dia_local(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="b505-reporte", email="b505@test.com"
    )
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    admin = (
        await test_session.execute(select(User).where(User.email == "b505@test.com"))
    ).scalar_one()
    service = (
        await test_session.execute(
            select(Service).where(Service.public_id == service_public_id)
        )
    ).scalar_one()
    staff = (
        await test_session.execute(select(Staff).where(Staff.id == staff_public_id))
    ).scalar_one()

    dia = _dia_local_futuro()
    # 22:30 ART del dia D se persiste a la 01:30Z del dia D+1.
    starts_at = local_to_utc(dia, time(22, 30))
    turno = Appointment(
        service_id=service.id,
        staff_id=staff.id,
        store_id=store.id,
        client_id=admin.id,
        client_name="Cliente Noche",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        duration_minutes=30,
        price_amount=Decimal("10000.00"),
        idempotency_key="b505-turno-noche",
    )
    test_session.add(turno)
    await test_session.commit()

    # Un bloqueo del mismo dia (10:00-11:00 ART) para que el reporte de
    # profesionales recorte contra los limites del rango, que ahora son aware.
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff_public_id,
            "starts_at": local_to_utc(dia, time(10, 0)).isoformat(),
            "ends_at": local_to_utc(dia, time(11, 0)).isoformat(),
            "reason": "Almuerzo",
        },
    )
    assert bloqueo.status_code in {200, 201}, bloqueo.text

    def rango(d: date) -> dict[str, str]:
        return {"from_date": d.isoformat(), "to_date": d.isoformat()}

    # El reporte del dia D contiene el turno; el del dia D+1, no.
    en_su_dia = await client.get(
        "/reports/summary", params=rango(dia), headers=auth_headers(token)
    )
    assert en_su_dia.status_code == 200, en_su_dia.text
    cuerpo = en_su_dia.json()
    assert [t["public_id"] for t in cuerpo["appointments"]] == [turno.id]
    assert cuerpo["stats"]["total_appointments"] == 1
    # La cohorte compara la primera visita (que vuelve de la base) con el
    # limite del rango: el cliente es nuevo en el dia D.
    assert cuerpo["client_stats"]["new_clients"] == 1

    al_dia_siguiente = await client.get(
        "/reports/summary",
        params=rango(dia + timedelta(days=1)),
        headers=auth_headers(token),
    )
    assert al_dia_siguiente.status_code == 200, al_dia_siguiente.text
    assert al_dia_siguiente.json()["stats"]["total_appointments"] == 0

    profesionales = await client.get(
        "/reports/professionals", params=rango(dia), headers=auth_headers(token)
    )
    assert profesionales.status_code == 200, profesionales.text
    pro = profesionales.json()["professionals"][0]
    assert pro["appointments"] == 1
    assert pro["blocked_minutes"] == 60
