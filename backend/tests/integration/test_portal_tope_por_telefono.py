"""Tope de turnos futuros por telefono en el portal (paquete antiabuso, S2).

2026-10-22. Sintoma: reservar en el portal es anonimo y un mismo telefono
tomaba todos los cupos que quisiera (un bot, o alguien que reserva "por las
dudas" toda la semana). Ahora una reserva publica con un telefono que ya tiene
``MAX_FUTURE_BOOKINGS_PER_PHONE`` (3) turnos futuros activos (pendiente,
esperando la sena o confirmado) en ESA tienda es 409
``TOO_MANY_FUTURE_BOOKINGS``, antes de escribir. Cuentan todos, sin importar
quien los cargo (el panel tambien); el panel nunca se limita. La carrera
(conteo y alta concurrentes) la cierra el lock de la ficha del cliente:
``tests/postgres/test_pg_tope_por_telefono.py``.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from tests.integration.test_caracterizacion_alta_publica import (
    _reserva,
    _Tienda,
    _tienda,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

MENSAJE = (
    "Ya tenés 3 turnos reservados en esta tienda. Si necesitás otro, "
    "escribile a la tienda."
)


def _a_las(t: _Tienda, horas: int) -> str:
    return (t.slot + timedelta(hours=horas)).isoformat()


async def _reservar(client: AsyncClient, t: _Tienda, clave: str, horas: int) -> int:
    res = await client.post(
        "/public/appointments",
        json=_reserva(t, clave, starts_at=_a_las(t, horas)),
    )
    return res.status_code


async def _otra_tienda(client: AsyncClient, base: _Tienda, slug: str) -> _Tienda:
    """Segunda tienda con su propio profesional (el email del personal es
    unico global, regla 16) y la misma jornada que ``base``."""
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@t.com")
    await add_staff_schedule(client, token, staff, target_date=base.slot)
    return _Tienda(store, token, service, staff, base.slot)


async def _turnos(session: AsyncSession) -> int:
    session.expire_all()
    return int(await session.scalar(select(func.count()).select_from(Appointment)) or 0)


@pytest.mark.asyncio
async def test_el_cuarto_turno_futuro_del_mismo_telefono_es_409(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    t = await _tienda(client, "tope-tel")
    for i in range(3):
        assert await _reservar(client, t, f"tope-tel-{i:04d}", i) == 201

    cuarto = await client.post(
        "/public/appointments",
        json=_reserva(t, "tope-tel-0003", starts_at=_a_las(t, 3)),
    )

    assert cuarto.status_code == 409, cuarto.text
    assert cuarto.json()["error_code"] == "TOO_MANY_FUTURE_BOOKINGS"
    assert cuarto.json()["message"] == MENSAJE
    assert await _turnos(test_session) == 3


@pytest.mark.asyncio
async def test_el_replay_del_tercero_devuelve_la_misma_reserva(
    client: AsyncClient,
) -> None:
    """El tope no rompe la idempotencia: reintentar la tercera reserva con su
    misma clave devuelve el mismo turno, no un 409."""
    t = await _tienda(client, "tope-tel-replay")
    for i in range(2):
        assert await _reservar(client, t, f"tope-replay-{i:04d}", i) == 201
    cuerpo = _reserva(t, "tope-replay-0002", starts_at=_a_las(t, 2))
    tercera = await client.post("/public/appointments", json=cuerpo)
    assert tercera.status_code == 201, tercera.text

    replay = await client.post("/public/appointments", json=cuerpo)

    assert replay.status_code == 201, replay.text
    assert replay.json()["public_id"] == tercera.json()["public_id"]


@pytest.mark.asyncio
async def test_cuentan_los_del_panel_pero_el_panel_no_se_limita(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    t = await _tienda(client, "tope-tel-panel")
    # El panel le carga tres turnos al mismo telefono, y un cuarto: sin tope.
    for i in range(4):
        alta = await client.post(
            "/appointments/",
            headers=auth_headers(t.token),
            json={
                "service_id": t.service,
                "staff_id": t.staff,
                "starts_at": _a_las(t, i),
                "client_name": "Cliente Caracterizado",
                "client_phone": "+5491155558001",
                "idempotency_key": f"tope-panel-{i:04d}",
            },
        )
        assert alta.status_code == 201, alta.text

    portal = await client.post(
        "/public/appointments",
        json=_reserva(t, "tope-panel-portal", starts_at=_a_las(t, 5)),
    )

    assert portal.status_code == 409, portal.text
    assert portal.json()["error_code"] == "TOO_MANY_FUTURE_BOOKINGS"
    assert await _turnos(test_session) == 4


@pytest.mark.asyncio
async def test_no_cuentan_cancelados_pasados_ni_otra_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    t = await _tienda(client, "tope-tel-cuenta")
    otra = await _otra_tienda(client, t, "tope-tel-otra")
    for i in range(3):
        assert await _reservar(client, otra, f"tope-otra-{i:04d}", i) == 201
    for i in range(3):
        assert await _reservar(client, t, f"tope-cuenta-{i:04d}", i) == 201
    test_session.expire_all()
    primero = (
        await test_session.execute(
            select(Appointment)
            .where(Appointment.idempotency_key == "tope-cuenta-0000")
            .limit(1)
        )
    ).scalar_one()
    # Un turno que ya paso, confirmado, del mismo cliente: no es futuro.
    ayer = t.slot - timedelta(days=6)
    test_session.add(
        Appointment(
            store_id=primero.store_id,
            staff_id=primero.staff_id,
            service_id=primero.service_id,
            client_id=primero.client_id,
            client_name=primero.client_name,
            client_email=primero.client_email,
            client_phone=primero.client_phone,
            starts_at=ayer,
            ends_at=ayer + timedelta(minutes=30),
            duration_minutes=30,
            price_amount=Decimal("10000"),
            status="confirmed",
        )
    )
    await test_session.commit()
    primero_id = primero.id

    cancelado = await client.patch(
        f"/appointments/{primero_id}/cancel", headers=auth_headers(t.token)
    )
    assert cancelado.status_code == 200, cancelado.text

    cuarto = await client.post(
        "/public/appointments",
        json=_reserva(t, "tope-cuenta-0003", starts_at=_a_las(t, 3)),
    )

    assert cuarto.status_code == 201, cuarto.text
