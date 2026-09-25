"""Fechas lejanas en altas y reprogramaciones: 422 solo lo que desborda.

2026-09-24/25, revision de perf/f4-back. Sintoma: un ``starts_at`` como
9999-12-31T23:59Z hacia desbordar ``starts_at + duracion`` (``OverflowError``,
500 por el handler generico) en la reserva publica, en la reprogramacion del
panel y del cliente, y en la reserva desde la lista de espera.

La primera correccion acoto con el horizonte de 120 dias y la revision la
rechazo: el front actual manda fechas libres por esos caminos (el "Nuevo
turno" del panel reserva por ``POST /public/appointments``; "Mis turnos"
reprograma con fecha y hora libres), y cortar en 120 dias era un cambio de
producto escondido en un arreglo de 500. Ahora las cotas son anchas y solo
cortan lo absurdo:

- Reservar y reprogramar (portal, panel, alta para un cliente): hasta 2
  anios hacia adelante (``MAX_BOOKING_AHEAD``). Al cliente lo sigue acotando
  la grilla de ``/public/availability`` (120 dias).
- Reservar desde la lista de espera: entre hace 2 anios y dentro de 2 anios.
  Si se rechazan reservas en el pasado es decision del dueno.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from tests.integration.test_caracterizacion_alta_publica import _reserva, _tienda
from tests.integration.test_caracterizacion_autogestion import TELEFONO, _con_turno
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

LEJANO = "9999-12-31T23:59:00+00:00"
ANTIGUO = "0001-01-01T01:00:00+00:00"
# Mismo dia de la semana y hora que el slot de la tienda (el horario del
# profesional es de ese dia): 57 y 105 semanas.
CASI_UN_ANIO_Y_MEDIO = timedelta(weeks=57)
MAS_DE_DOS_ANIOS = timedelta(weeks=105)


def _en(dias: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()


@pytest.mark.asyncio
async def test_reserva_publica_hasta_dos_anios(client: AsyncClient) -> None:
    t = await _tienda(client, "horiz-publica")

    lejos = await client.post(
        "/public/appointments",
        json=_reserva(
            t,
            "horiz-publica-0400",
            starts_at=(t.slot + CASI_UN_ANIO_Y_MEDIO).isoformat(),
        ),
    )
    assert lejos.status_code == 201, lejos.text

    for i, cuando in enumerate((LEJANO, (t.slot + MAS_DE_DOS_ANIOS).isoformat())):
        res = await client.post(
            "/public/appointments",
            json=_reserva(t, f"horiz-publica-{i:04d}", starts_at=cuando),
        )
        assert res.status_code == 422, (cuando, res.text)


@pytest.mark.asyncio
async def test_reprogramar_desde_el_panel_mas_alla_de_dos_anios_422(
    client: AsyncClient,
) -> None:
    t = await _tienda(client, "horiz-panel")
    alta = await client.post(
        "/appointments/",
        headers=auth_headers(t.token),
        json={
            "service_id": t.service,
            "staff_id": t.staff,
            "starts_at": t.slot.isoformat(),
            "idempotency_key": "horiz-panel-alta",
        },
    )
    assert alta.status_code == 201, alta.text

    for i, cuando in enumerate((LEJANO, _en(731))):
        res = await client.patch(
            f"/appointments/{alta.json()['public_id']}/reschedule",
            headers=auth_headers(t.token),
            json={"new_starts_at": cuando, "idempotency_key": f"horiz-panel-rs-{i}"},
        )
        assert res.status_code == 422, (cuando, res.text)


@pytest.mark.asyncio
async def test_reprogramar_desde_el_portal_mas_alla_de_dos_anios_422(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _con_turno(client, monkeypatch, "horiz-cliente")

    for i, cuando in enumerate((LEJANO, (t.slot + MAS_DE_DOS_ANIOS).isoformat())):
        res = await client.patch(
            f"/public/client/appointments/{turno}/reschedule",
            json={
                "phone": TELEFONO,
                "new_starts_at": cuando,
                "idempotency_key": f"horiz-cliente-rs-{i}",
            },
        )
        assert res.status_code == 422, (cuando, res.text)


@pytest.mark.asyncio
async def test_un_turno_despues_de_los_120_dias_se_puede_mover(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un turno que ya esta mas alla de +120 dias (lo cargo el panel) se
    puede cambiar de hora desde "Mis turnos"."""
    t, base_id = await _con_turno(client, monkeypatch, "horiz-cliente-lejos")
    base = (
        await test_session.execute(select(Appointment).where(Appointment.id == base_id))
    ).scalar_one()
    inicio = t.slot + timedelta(weeks=21)  # 147 dias, mismo dia de la semana
    lejano = Appointment(
        store_id=base.store_id,
        staff_id=base.staff_id,
        service_id=base.service_id,
        client_id=base.client_id,
        client_name=base.client_name,
        client_email=base.client_email,
        client_phone=base.client_phone,
        starts_at=inicio,
        ends_at=inicio + timedelta(minutes=30),
        duration_minutes=30,
        price_amount=Decimal("10000"),
        status="confirmed",
    )
    test_session.add(lejano)
    await test_session.commit()

    res = await client.patch(
        f"/public/client/appointments/{lejano.id}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (inicio + timedelta(hours=1)).isoformat(),
            "idempotency_key": "horiz-cliente-lejos-1",
        },
    )

    assert res.status_code == 200, res.text


async def _lista_de_espera(client: AsyncClient, slug: str) -> tuple[str, str]:
    """Tienda con un profesional que atiende todo el dia, todos los dias, y
    una persona anotada en la lista de espera; devuelve token y entrada."""
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    headers = auth_headers(token)
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@t.com")
    for dia in range(7):
        horario = await client.post(
            f"/staff/{staff}/schedules",
            headers=headers,
            json={"day_of_week": dia, "start_time": "00:00:00", "end_time": "23:59:00"},
        )
        assert horario.status_code == 200, horario.text
    manana = datetime.now(timezone.utc) + timedelta(days=1)
    anotado = await client.post(
        "/public/waitlist",
        json={
            "store_public_id": store,
            "service_id": service,
            "window_starts_at": manana.isoformat(),
            "window_ends_at": (manana + timedelta(days=2)).isoformat(),
            "client_name": "En Espera",
            "client_phone": "+5491100001111",
        },
    )
    assert anotado.status_code == 201, anotado.text
    return token, str(anotado.json()["public_id"])


@pytest.mark.asyncio
async def test_reservar_desde_la_lista_de_espera_fuera_de_rango_422(
    client: AsyncClient,
) -> None:
    token, entrada = await _lista_de_espera(client, "horiz-espera")

    casos: list[Any] = [LEJANO, ANTIGUO, _en(731), _en(-731)]
    for cuando in casos:
        res = await client.post(
            f"/waitlist/{entrada}/book",
            headers=auth_headers(token),
            json={"starts_at": cuando},
        )
        assert res.status_code == 422, (cuando, res.text)


@pytest.mark.asyncio
async def test_reservar_desde_la_lista_de_espera_un_turno_que_ya_paso(
    client: AsyncClient,
) -> None:
    """El dueno carga despues a quien ya atendio (o el horario por defecto,
    las 10:00, ya paso): sin piso en el pasado."""
    token, entrada = await _lista_de_espera(client, "horiz-espera-pasado")
    # En punto: un servicio de 30 minutos que empieza en punto nunca cruza
    # la medianoche, y el horario del profesional cubre todo el dia.
    hace_dos_horas = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(
        minute=0, second=0, microsecond=0
    )

    res = await client.post(
        f"/waitlist/{entrada}/book",
        headers=auth_headers(token),
        json={"starts_at": hace_dos_horas.isoformat()},
    )

    assert res.status_code == 201, res.text
