"""Fechas lejanas en altas y reprogramaciones.

2026-09-24/25, revision de perf/f4-back. Sintoma: un ``starts_at`` como
9999-12-31T23:59Z hacia desbordar ``starts_at + duracion`` (``OverflowError``,
500 por el handler generico) en la reserva publica, en la reprogramacion del
panel y del cliente, y en la reserva desde la lista de espera. Desde entonces
toda reserva y reprogramacion corta lo absurdo con ``MAX_BOOKING_AHEAD`` (2
anios hacia adelante; la lista de espera y el panel tambien 2 hacia atras).

2026-10-22, paquete antiabuso (D-20261022-01, propuesta por Mateo, pendiente
de OK del dueno): el portal tiene ademas horizonte de producto. Una reserva
publica no empieza despues de hoy + 120 dias locales
(``BOOKING_HORIZON_DAYS``), y "Mis turnos" mueve un turno hasta hoy + 120
dias, o hasta el dia de su inicio actual si es mas tarde (un turno que la
tienda cargo mas alla se sigue pudiendo mover). Pasarse es 422
``BOOKING_HORIZON_EXCEEDED``. El panel y la lista de espera del lado de la
tienda conservan solo la cota de 2 anios.
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
from modules.notifications.tasks import (
    EVENT_APPOINTMENT_CONFIRMED,
    EVENT_APPOINTMENT_RESCHEDULED,
)
from modules.payments.model import OutboxMessage
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
# profesional es de ese dia): 57 y 105 semanas. El slot esta a 5 dias, asi
# que 16 semanas despues cae a 117 dias (adentro de los 120) y 17 semanas
# despues a 124 (afuera).
CASI_UN_ANIO_Y_MEDIO = timedelta(weeks=57)
MAS_DE_DOS_ANIOS = timedelta(weeks=105)
DENTRO_DEL_HORIZONTE = timedelta(weeks=16)
FUERA_DEL_HORIZONTE = timedelta(weeks=17)
MENSAJE_HORIZONTE = "Podés reservar hasta 120 días adelante."


def _en(dias: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()


@pytest.mark.asyncio
async def test_reserva_publica_hasta_120_dias(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    t = await _tienda(client, "horiz-publica")

    adentro = await client.post(
        "/public/appointments",
        json=_reserva(
            t,
            "horiz-publica-0117",
            starts_at=(t.slot + DENTRO_DEL_HORIZONTE).isoformat(),
        ),
    )
    assert adentro.status_code == 201, adentro.text

    afuera = await client.post(
        "/public/appointments",
        json=_reserva(
            t,
            "horiz-publica-0124",
            starts_at=(t.slot + FUERA_DEL_HORIZONTE).isoformat(),
        ),
    )
    assert afuera.status_code == 422, afuera.text
    assert afuera.json()["error_code"] == "BOOKING_HORIZON_EXCEEDED"
    assert afuera.json()["message"] == MENSAJE_HORIZONTE
    # Antes de escribir: el rechazo no deja turno.
    test_session.expire_all()
    turnos = (await test_session.execute(select(Appointment))).scalars().all()
    assert len(turnos) == 1

    # La cota contra el desborde sigue: 422 de validacion, nunca 500.
    for i, cuando in enumerate((LEJANO, (t.slot + MAS_DE_DOS_ANIOS).isoformat())):
        res = await client.post(
            "/public/appointments",
            json=_reserva(t, f"horiz-publica-{i:04d}", starts_at=cuando),
        )
        assert res.status_code == 422, (cuando, res.text)


@pytest.mark.asyncio
async def test_el_panel_reserva_mas_alla_de_los_120_dias(client: AsyncClient) -> None:
    """El horizonte es del portal: el panel conserva solo los 2 anios."""
    t = await _tienda(client, "horiz-panel-lejos")

    alta = await client.post(
        "/appointments/",
        headers=auth_headers(t.token),
        json={
            "service_id": t.service,
            "staff_id": t.staff,
            "starts_at": (t.slot + CASI_UN_ANIO_Y_MEDIO).isoformat(),
            "idempotency_key": "horiz-panel-lejos-alta",
        },
    )

    assert alta.status_code == 201, alta.text


@pytest.mark.asyncio
async def test_reprogramar_desde_el_portal_hasta_120_dias(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _con_turno(client, monkeypatch, "horiz-cliente-120")

    afuera = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (t.slot + FUERA_DEL_HORIZONTE).isoformat(),
            "idempotency_key": "horiz-cliente-120-rs-1",
        },
    )
    assert afuera.status_code == 422, afuera.text
    assert afuera.json()["error_code"] == "BOOKING_HORIZON_EXCEEDED"
    assert afuera.json()["message"] == MENSAJE_HORIZONTE

    adentro = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (t.slot + DENTRO_DEL_HORIZONTE).isoformat(),
            "idempotency_key": "horiz-cliente-120-rs-2",
        },
    )
    assert adentro.status_code == 200, adentro.text


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
    lejano_id = lejano.id

    # Mas alla del dia de su inicio actual no: el tope es max(hoy + 120, ese
    # dia), asi que una semana despues es 422 y el turno no se toca.
    mas_lejos = await client.patch(
        f"/public/client/appointments/{lejano_id}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (inicio + timedelta(weeks=1)).isoformat(),
            "idempotency_key": "horiz-cliente-lejos-0",
        },
    )
    assert mas_lejos.status_code == 422, mas_lejos.text
    assert mas_lejos.json()["error_code"] == "BOOKING_HORIZON_EXCEEDED"

    res = await client.patch(
        f"/public/client/appointments/{lejano_id}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (inicio + timedelta(hours=1)).isoformat(),
            "idempotency_key": "horiz-cliente-lejos-1",
        },
    )

    assert res.status_code == 200, res.text

    # Y hacia antes, aunque siga fuera de los 120 dias, tambien se mueve.
    antes = await client.patch(
        f"/public/client/appointments/{res.json()['public_id']}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (inicio - timedelta(weeks=1)).isoformat(),
            "idempotency_key": "horiz-cliente-lejos-2",
        },
    )
    assert antes.status_code == 200, antes.text


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
            "client_email": "c5491100001111@example.com",
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
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El dueno carga despues a quien ya atendio (o el horario por defecto,
    las 10:00, ya paso): sin piso en el pasado (decision de Mateo,
    2026-09-25: la tienda puede, el cliente final no). Sin mail de "turno
    confirmado" para un turno que ya empezo."""
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
    avisos = (
        (
            await test_session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == EVENT_APPOINTMENT_CONFIRMED
                )
            )
        )
        .scalars()
        .all()
    )
    assert avisos == []


@pytest.mark.asyncio
async def test_reprogramar_desde_el_panel_a_un_horario_que_ya_paso(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Decision de Mateo (2026-09-25): la tienda puede reservar un horario
    que ya paso, asi que tambien puede corregir un walk-in mal cargado
    moviendolo a la hora real, hasta el piso contra el desborde (2 anios).
    Sin mail de "tu turno cambio" para un inicio que ya paso."""
    t = await _tienda(client, "horiz-panel-pasado")
    alta = await client.post(
        "/appointments/",
        headers=auth_headers(t.token),
        json={
            "service_id": t.service,
            "staff_id": t.staff,
            "starts_at": t.slot.isoformat(),
            "idempotency_key": "horiz-panel-pasado-alta",
        },
    )
    assert alta.status_code == 201, alta.text
    hace_tres_horas = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(
        second=0, microsecond=0
    )

    movido = await client.patch(
        f"/appointments/{alta.json()['public_id']}/reschedule",
        headers=auth_headers(t.token),
        json={
            "new_starts_at": hace_tres_horas.isoformat(),
            "idempotency_key": "horiz-panel-pasado-rs-1",
            # D-20260929-04: la hora a la que corre el test no se controla y
            # fuera de la jornada solo mueve el admin, explicito.
            "allow_outside_schedule": True,
        },
    )
    assert movido.status_code == 200, movido.text

    muy_viejo = await client.patch(
        f"/appointments/{movido.json()['public_id']}/reschedule",
        headers=auth_headers(t.token),
        json={
            "new_starts_at": _en(-731),
            "idempotency_key": "horiz-panel-pasado-rs-2",
        },
    )
    assert muy_viejo.status_code == 422, muy_viejo.text

    avisos = (
        (
            await test_session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == EVENT_APPOINTMENT_RESCHEDULED
                )
            )
        )
        .scalars()
        .all()
    )
    assert avisos == []
