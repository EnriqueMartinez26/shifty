"""La agenda diaria del panel corta el dia en hora argentina, no en UTC.

Audit B1-08 (2026-09-17), regla 24 de CLAUDE.md. Sintoma: ``get_by_date``
armaba el dia como ``[00:00Z, 24:00Z)``, o sea de las 21:00 del dia anterior
a las 20:59 del dia pedido en hora argentina. Un turno de las 22:00 ART (01:00
UTC del dia siguiente) no aparecia en la agenda del dia que el dueno abria y
si en la del dia siguiente. ``search_appointments`` tenia el mismo corte
(ademas con datetimes naive). La disponibilidad ya usaba ``local_to_utc``.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from core.utils import ARGENTINA_TZ
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _turno_de_las_22_local(client: AsyncClient) -> tuple[str, str, datetime]:
    """Reserva un turno a las 22:00 hora argentina y devuelve (token, id, dia)."""
    store, token = await register_and_login(
        client, slug="agenda-noche", email="agenda-noche@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = (datetime.now(timezone.utc) + timedelta(days=5)).date()
    horario = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": dia.weekday(),
            "start_time": "20:00:00",
            "end_time": "23:00:00",
        },
    )
    assert horario.status_code == 200, horario.text
    slots = (
        await client.get(
            "/public/availability",
            params={
                "store_public_id": store,
                "service_id": service,
                "date": dia.isoformat(),
                "force_all": "true",
            },
        )
    ).json()
    slot = next(s for s in slots if s["start_time"] == "22:00:00")

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot["starts_at"],
            "client_name": "Noche",
            "client_phone": "+5491155550808",
            "idempotency_key": "agenda-noche-2200",
        },
    )
    assert reserva.status_code == 201, reserva.text
    inicio = datetime.fromisoformat(reserva.json()["starts_at"])
    if inicio.tzinfo is None:  # SQLite devuelve el UTC naive
        inicio = inicio.replace(tzinfo=timezone.utc)
    # Precondicion del sintoma: el instante cae en el dia UTC siguiente.
    assert inicio.astimezone(timezone.utc).date() == dia + timedelta(days=1)
    assert inicio.astimezone(ARGENTINA_TZ).date() == dia
    return (
        token,
        reserva.json()["public_id"],
        datetime.combine(dia, datetime.min.time()),
    )


@pytest.mark.asyncio
async def test_la_agenda_del_dia_incluye_el_turno_de_las_22_hora_argentina(
    client: AsyncClient,
) -> None:
    token, turno, dia = await _turno_de_las_22_local(client)
    fecha = dia.date()
    siguiente = fecha + timedelta(days=1)

    agenda = await client.get(
        f"/appointments/?date={fecha.isoformat()}", headers=auth_headers(token)
    )
    assert agenda.status_code == 200, agenda.text
    assert [item["public_id"] for item in agenda.json()] == [turno], agenda.text

    agenda_siguiente = await client.get(
        f"/appointments/?date={siguiente.isoformat()}", headers=auth_headers(token)
    )
    assert agenda_siguiente.status_code == 200, agenda_siguiente.text
    assert agenda_siguiente.json() == [], agenda_siguiente.text


@pytest.mark.asyncio
async def test_la_busqueda_por_rango_de_fechas_corta_en_hora_argentina(
    client: AsyncClient,
) -> None:
    token, turno, dia = await _turno_de_las_22_local(client)
    fecha = dia.date().isoformat()
    siguiente = (dia.date() + timedelta(days=1)).isoformat()

    mismo_dia = await client.get(
        "/appointments/search",
        headers=auth_headers(token),
        params={"from_date": fecha, "to_date": fecha},
    )
    assert mismo_dia.status_code == 200, mismo_dia.text
    assert [r["public_id"] for r in mismo_dia.json()["results"]] == [turno]

    dia_siguiente = await client.get(
        "/appointments/search",
        headers=auth_headers(token),
        params={"from_date": siguiente, "to_date": siguiente},
    )
    assert dia_siguiente.status_code == 200, dia_siguiente.text
    assert dia_siguiente.json()["results"] == [], dia_siguiente.text
