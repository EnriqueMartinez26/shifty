"""La disponibilidad publica filtrada no esconde la agenda con duraciones libres.

Audit B1-01 + B6-03 (2026-09-18). Sintoma: el filtro de huecos de
``get_available_slots`` (camino por defecto del portal, ``force_all=false``)
conservaba un slot solo si era el primero, el ultimo, o si su ``ends_at``
coincidia como STRING con el ``starts_at`` de otro. Con la grilla de 15
minutos eso solo pasa si la duracion es multiplo de 15: con un servicio de 40
minutos la agenda de un dia entero quedaba en 2 slots, aunque los del medio se
podian reservar por ``POST /public/appointments``.

Decision (OK global del usuario, sugerencia del brief): "strict gap filtering"
es no ofrecer huecos irreservables, no esconder todo. Un slot libre se ofrece
si queda pegado (a menos de un paso de grilla) al borde de su hueco libre, o si
lo que deja a cada lado todavia admite otro turno del mismo servicio alineado a
la grilla. No se acota ``duration_minutes``: 40, 50 y 70 minutos son reales.
Las horas se comparan en hora argentina (``start_time``).
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient

from core.utils import local_to_utc
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_staff,
    register_and_login,
)


async def _tienda(
    client: AsyncClient, slug: str, duracion: int
) -> tuple[str, str, str, str, date]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    servicio = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={
            "name": f"Servicio {duracion}",
            "duration_minutes": duracion,
            "price": 1000,
        },
    )
    assert servicio.status_code == 201, servicio.text
    service = str(servicio.json()["public_id"])
    staff = await create_staff(client, token, service)
    dia = (datetime.now(timezone.utc) + timedelta(days=5)).date()
    horario = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": dia.weekday(),
            "start_time": "09:00:00",
            "end_time": "13:00:00",
        },
    )
    assert horario.status_code == 200, horario.text
    return store, token, service, staff, dia


async def _ofrecidos(
    client: AsyncClient, store: str, service: str, dia: date
) -> list[str]:
    """Horas locales de los slots LIBRES que ve el cliente por defecto."""
    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": dia.isoformat(),
        },
    )
    assert res.status_code == 200, res.text
    slots: list[dict[str, Any]] = res.json()
    return [s["start_time"][:5] for s in slots if s["status"] == "available"]


def _utc(dia: date, hhmm: str) -> str:
    hora, minuto = (int(p) for p in hhmm.split(":"))
    return local_to_utc(
        dia, datetime.min.time().replace(hour=hora, minute=minuto)
    ).isoformat()


@pytest.mark.asyncio
async def test_servicio_de_40_minutos_en_agenda_vacia(client: AsyncClient) -> None:
    store, _token, service, _staff, dia = await _tienda(client, "grilla-40", 40)

    ofrecidos = await _ofrecidos(client, store, service, dia)

    # 09:15 y 09:30 dejarian 15/30 minutos invendibles adelante; 11:45 y 12:00
    # dejarian 35/20 atras. 12:15 es el ultimo que entra (sobran 5, menos de
    # un paso de grilla). Antes: solo ["09:00", "12:15"].
    assert ofrecidos == [
        "09:00",
        "09:45",
        "10:00",
        "10:15",
        "10:30",
        "10:45",
        "11:00",
        "11:15",
        "11:30",
        "12:15",
    ]


@pytest.mark.asyncio
async def test_servicio_de_50_minutos_con_un_turno_en_el_medio(
    client: AsyncClient,
) -> None:
    store, _token, service, staff, dia = await _tienda(client, "grilla-50", 50)
    turno = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": _utc(dia, "11:00"),
            "client_name": "Ocupa",
            "client_phone": "+5491155552001",
            "accepts_terms": True,
            "idempotency_key": "grilla-50-turno-0001",
        },
    )
    assert turno.status_code == 201, turno.text

    ofrecidos = await _ofrecidos(client, store, service, dia)

    # Hueco [09:00, 11:00): pegados al borde 09:00 y 10:00 (10:00-10:50 deja
    # 10 minutos, menos que un paso). Hueco [11:50, 13:00): 12:00, primer
    # paso de grilla despues del turno. Antes: ["09:00", "12:00"].
    assert ofrecidos == ["09:00", "10:00", "12:00"]


@pytest.mark.asyncio
async def test_servicio_de_70_minutos_con_un_bloqueo_en_el_medio(
    client: AsyncClient,
) -> None:
    store, token, service, staff, dia = await _tienda(client, "grilla-70", 70)
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": _utc(dia, "10:30"),
            "ends_at": _utc(dia, "11:00"),
            "reason": "Tramite",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text

    ofrecidos = await _ofrecidos(client, store, service, dia)

    # Hueco [09:00, 10:30): solo entran 09:00 y 09:15, las dos pegadas a un
    # borde. Hueco [11:00, 13:00): 11:00 y 11:45 (11:15 y 11:30 dejarian 15 y
    # 30 minutos invendibles adelante). Antes: ["09:00", "11:45"].
    assert ofrecidos == ["09:00", "09:15", "11:00", "11:45"]


@pytest.mark.asyncio
async def test_force_all_sigue_mostrando_toda_la_grilla(client: AsyncClient) -> None:
    store, _token, service, _staff, dia = await _tienda(client, "grilla-todo", 40)
    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": dia.isoformat(),
            "force_all": "true",
        },
    )
    assert res.status_code == 200, res.text
    libres = [s["start_time"][:5] for s in res.json() if s["status"] == "available"]
    # 09:00 a 12:15 cada 15 minutos.
    assert len(libres) == 14 and libres[0] == "09:00" and libres[-1] == "12:15"


@pytest.mark.asyncio
async def test_cada_slot_ofrecido_se_puede_reservar(client: AsyncClient) -> None:
    """Lo que se ofrece filtrado sigue siendo reservable (el alta revalida)."""
    store, _token, service, staff, dia = await _tienda(client, "grilla-reserva", 50)
    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": dia.isoformat(),
        },
    )
    assert res.status_code == 200, res.text
    primero = next(s for s in res.json() if s["status"] == "available")
    alta = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": primero["starts_at"],
            "client_name": "Reserva",
            "client_phone": "+5491155552002",
            "accepts_terms": True,
            "idempotency_key": "grilla-reserva-0001",
        },
    )
    assert alta.status_code == 201, alta.text
    # La reserva invalida el cache: el slot ya no se ofrece como libre.
    assert primero["start_time"][:5] not in await _ofrecidos(
        client, store, service, dia
    )
