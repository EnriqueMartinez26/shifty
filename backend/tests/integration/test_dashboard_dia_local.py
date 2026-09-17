"""El panel define "hoy" y "la semana" con el calendario argentino, no el UTC.

2026-09-17, hallazgo B5-04: ``/dashboard/summary`` armaba ``start_today`` con
``datetime(now.year, now.month, now.day, tzinfo=utc)`` y la semana restando
``timedelta`` sobre eso. Argentina es UTC-3: un turno del lunes 22:30 hora
local se persiste 01:30Z del martes y no contaba en ``appointments_today`` del
lunes; el domingo a las 21:00 ART el panel ya mostraba la semana siguiente y
``weekly_revenue`` caia a 0. Regla 24 de CLAUDE.md: "un dia" de negocio es
aritmetica de calendario con zona (``core.utils.local_to_utc``), no
``timedelta(hours=24)`` sobre medianoche UTC.

El reloj se congela para que el borde sea el mismo a cualquier hora en que
corra la suite: "ahora" es el miercoles 2026-09-16 a las 15:00 ART.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import core.utils
import modules.dashboard.router
from core.utils import local_to_utc
from modules.appointments.model import Appointment
from modules.payments.model import Payment, PaymentStatus
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

HOY_LOCAL = date(2026, 9, 16)  # miercoles
AHORA = local_to_utc(HOY_LOCAL, time(15, 0))


class _RelojCongelado(datetime):
    """``datetime`` cuyo ``now`` siempre devuelve AHORA; el resto es real."""

    @classmethod
    def now(cls, tz: object = None) -> "_RelojCongelado":
        fixed = AHORA if tz is None else AHORA.astimezone(cast(timezone, tz))
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


async def _sembrar_turno(
    session: AsyncSession,
    *,
    store: Store,
    admin: User,
    service: Service,
    staff: Staff,
    dia_local: date,
    hora_local: time,
    cobrado: Decimal | None,
) -> None:
    starts_at = local_to_utc(dia_local, hora_local)
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
        idempotency_key=f"b504-{dia_local.isoformat()}-{hora_local.isoformat()}",
    )
    session.add(turno)
    await session.flush()
    if cobrado is not None:
        session.add(
            Payment(
                store_id=store.id,
                appointment_id=turno.id,
                amount=cobrado,
                status=PaymentStatus.MANUAL_CONFIRMED.value,
                provider="manual",
            )
        )
    await session.commit()


@pytest.mark.asyncio
async def test_hoy_y_la_semana_del_panel_son_dias_argentinos(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core.utils, "datetime", _RelojCongelado)
    monkeypatch.setattr(modules.dashboard.router, "datetime", _RelojCongelado)

    store_public_id, token = await register_and_login(
        client, slug="b504-panel", email="b504@test.com"
    )
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    admin = (
        await test_session.execute(select(User).where(User.email == "b504@test.com"))
    ).scalar_one()
    service = (
        await test_session.execute(
            select(Service).where(Service.public_id == service_public_id)
        )
    ).scalar_one()
    staff = (
        await test_session.execute(select(Staff).where(Staff.id == staff_public_id))
    ).scalar_one()

    async def sembrar(dia_local: date, cobrado: Decimal | None) -> None:
        await _sembrar_turno(
            test_session,
            store=store,
            admin=admin,
            service=service,
            staff=staff,
            dia_local=dia_local,
            hora_local=time(22, 30),
            cobrado=cobrado,
        )

    # Hoy (miercoles) a las 22:30 ART = jueves 01:30Z: es un turno de HOY.
    await sembrar(HOY_LOCAL, cobrado=None)
    # Domingo 20 a las 22:30 ART = lunes 21 01:30Z: todavia es ESTA semana.
    await sembrar(date(2026, 9, 20), cobrado=Decimal("10000.00"))
    # Domingo 13 a las 22:30 ART = lunes 14 01:30Z: es la semana PASADA.
    await sembrar(date(2026, 9, 13), cobrado=Decimal("5000.00"))

    res = await client.get("/dashboard/summary", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    stats = res.json()["stats"]
    # Con el corte UTC: 0 turnos hoy (el de las 22:30 caia en manana) y la
    # semana valia 5000 (el domingo 13 entraba y el domingo 20 quedaba afuera).
    assert stats["appointments_today"] == 1
    assert stats["weekly_revenue"] == 10000.0
