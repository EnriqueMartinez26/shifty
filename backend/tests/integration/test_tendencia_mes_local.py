"""La tendencia mensual agrupa por mes ARGENTINO, no por mes UTC.

2026-09-18, seguimiento S-05 (revision de B5-05): ``get_trend`` armaba los
limites con ``datetime.combine(start_month, time.min)`` (medianoche UTC) y
agrupaba con ``date_trunc('month', starts_at)`` sobre el instante UTC. Un turno
del 31 de agosto a las 22:30 ART se persiste el 1 de septiembre 01:30Z y caia
en septiembre; el del 30 de septiembre a las 22:30 ART (1 de octubre 01:30Z)
quedaba afuera del mes en curso; y el del 31 de julio a las 22:30 ART entraba
en agosto. Regla 24: la hora local es presentacion y "un dia" (y un mes) de
negocio es calendario con zona.

Ademas ``date_trunc`` no existe en SQLite: el endpoint nunca se habia
ejercitado contra una base en la suite (solo con un ``execute`` falso).

El caso de cambio de anio es el mismo borde con la clave del anio en juego:
el 31/12 a las 22:30 ART ya es 1 de enero en UTC y tiene que contar en
diciembre del anio anterior.

Reloj congelado: "hoy" es el miercoles 2026-09-16 (ART), o el 15/01/2027 en
el caso de cambio de anio.
"""

from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import core.utils
from core.utils import local_to_utc
from modules.appointments.model import Appointment, AppointmentStatus
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

Turno = Callable[[date, time, AppointmentStatus], Awaitable[None]]


def _reloj(ahora: datetime) -> type[datetime]:
    """``datetime`` cuyo ``now`` siempre devuelve ``ahora``; el resto es real."""

    class _Reloj(datetime):
        @classmethod
        def now(cls, tz: object = None) -> "_Reloj":
            fixed = ahora if tz is None else ahora.astimezone(cast(timezone, tz))
            return cls(
                fixed.year,
                fixed.month,
                fixed.day,
                fixed.hour,
                fixed.minute,
                fixed.second,
                fixed.microsecond,
                fixed.tzinfo,
            )

    return _Reloj


async def _tienda(
    client: AsyncClient, test_session: AsyncSession, slug: str
) -> tuple[str, Turno]:
    """Tienda con un servicio y un profesional; devuelve el token y un
    sembrador de turnos en hora argentina."""
    email = f"{slug}@test.com"
    store_public_id, token = await register_and_login(client, slug=slug, email=email)
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(
        client, token, service_public_id, email=f"pro-{slug}@test.com"
    )
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    admin = (
        await test_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    servicio = (
        await test_session.execute(
            select(Service).where(Service.public_id == service_public_id)
        )
    ).scalar_one()
    staff = (
        await test_session.execute(select(Staff).where(Staff.id == staff_public_id))
    ).scalar_one()

    async def turno(dia: date, hora: time, estado: AppointmentStatus) -> None:
        starts_at = local_to_utc(dia, hora)
        test_session.add(
            Appointment(
                service_id=servicio.id,
                staff_id=staff.id,
                store_id=store.id,
                client_id=admin.id,
                client_name="Cliente",
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=30),
                duration_minutes=30,
                price_amount=Decimal("10000"),
                status=estado.value,
                idempotency_key=f"{slug}-{dia.isoformat()}-{hora.isoformat()}",
            )
        )
        await test_session.commit()

    return token, turno


def _punto(
    mes: str, total: int, completados: int, cancelados: int
) -> dict[str, str | int]:
    return {
        "month": mes,
        "total_appointments": total,
        "completed_appointments": completados,
        "cancelled_appointments": cancelados,
    }


@pytest.mark.asyncio
async def test_el_turno_del_31_a_las_2230_cuenta_en_su_mes(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ahora = local_to_utc(date(2026, 9, 16), time(15, 0))
    monkeypatch.setattr(core.utils, "datetime", _reloj(ahora))
    token, turno = await _tienda(client, test_session, "s05-tendencia")

    # 31/07 22:30 ART = 01/08 01:30Z: es de julio, fuera de la ventana.
    await turno(date(2026, 7, 31), time(22, 30), AppointmentStatus.COMPLETED)
    # 31/08 22:30 ART = 01/09 01:30Z: es de agosto.
    await turno(date(2026, 8, 31), time(22, 30), AppointmentStatus.COMPLETED)
    # 01/09 00:30 ART = 01/09 03:30Z: es de septiembre.
    await turno(date(2026, 9, 1), time(0, 30), AppointmentStatus.CANCELLED)
    # 30/09 22:30 ART = 01/10 01:30Z: sigue siendo del mes en curso.
    await turno(date(2026, 9, 30), time(22, 30), AppointmentStatus.PENDING)

    res = await client.get(
        "/reports/trend", params={"months": 2}, headers=auth_headers(token)
    )
    assert res.status_code == 200, res.text
    assert res.json()["points"] == [
        _punto("2026-08", 1, 1, 0),
        _punto("2026-09", 2, 0, 1),
    ]


@pytest.mark.asyncio
async def test_el_31_de_diciembre_a_las_2230_cuenta_en_diciembre_del_anio_viejo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ahora = local_to_utc(date(2027, 1, 15), time(15, 0))
    monkeypatch.setattr(core.utils, "datetime", _reloj(ahora))
    token, turno = await _tienda(client, test_session, "s05-anio")

    # 30/11 22:30 ART = 01/12 01:30Z: es de noviembre, fuera de la ventana.
    await turno(date(2026, 11, 30), time(22, 30), AppointmentStatus.COMPLETED)
    # 31/12 22:30 ART = 01/01/2027 01:30Z: es de diciembre de 2026.
    await turno(date(2026, 12, 31), time(22, 30), AppointmentStatus.COMPLETED)
    # 01/01 00:30 ART = 01/01/2027 03:30Z: es de enero de 2027.
    await turno(date(2027, 1, 1), time(0, 30), AppointmentStatus.CANCELLED)
    # 31/01 22:30 ART = 01/02/2027 01:30Z: sigue siendo del mes en curso.
    await turno(date(2027, 1, 31), time(22, 30), AppointmentStatus.PENDING)

    res = await client.get(
        "/reports/trend", params={"months": 2}, headers=auth_headers(token)
    )
    assert res.status_code == 200, res.text
    assert res.json()["points"] == [
        _punto("2026-12", 1, 1, 0),
        _punto("2027-01", 2, 0, 1),
    ]
