"""Rafaga del tope de turnos futuros por telefono (paquete antiabuso, S2).

N reservas publicas simultaneas del MISMO telefono, cada una con un
profesional distinto (asi el lock del profesional no las serializa): sin el
lock de la ficha del cliente todas contaban los mismos turnos previos y
entraban todas. Con ``FOR NO KEY UPDATE`` sobre la ficha antes de contar,
entran exactamente ``MAX_FUTURE_BOOKINGS_PER_PHONE`` (3) y el resto es 409
``TOO_MANY_FUTURE_BOOKINGS``, sin ningun 5xx. En SQLite el lock se ignora:
esta prueba solo vale contra Postgres real.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from modules.public_api.service import MAX_FUTURE_BOOKINGS_PER_PHONE
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

PROFESIONALES = 6
TELEFONO = "+5491155520001"


def _reserva(
    store: str, service: str, staff: str, slot: datetime, key: str
) -> dict[str, Any]:
    return {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": "Cliente Rafaga",
        "client_phone": TELEFONO,
        "accepts_terms": True,
        "idempotency_key": key,
    }


async def _turnos_futuros_del_telefono(owner_engine: AsyncEngine, store: str) -> int:
    async with owner_engine.connect() as conn:
        total = (
            await conn.execute(
                text(
                    "select count(*) from appointments a "
                    "join stores s on s.id = a.store_id "
                    "where s.public_id = :store and a.client_phone = :phone "
                    "and a.status in ('pending','pending_payment','confirmed') "
                    "and a.starts_at > now()"
                ),
                {"store": store, "phone": TELEFONO.lstrip("+")},
            )
        ).scalar_one()
        return cast(int, total)


@pytest.mark.asyncio
async def test_rafaga_del_mismo_telefono_deja_pasar_solo_el_tope(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, token = await register_and_login(
        client, app_sessions, slug="tope-rafaga", email="tope-rafaga@demo.com"
    )
    service = await create_service(client, token)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)
    staff_ids = []
    for i in range(PROFESIONALES):
        staff = await create_staff(
            client, token, service, email=f"pro-tope-{i}@demo.com"
        )
        await add_staff_schedule(client, token, staff, target_date=dia)
        staff_ids.append(staff)

    # La ficha del cliente tiene que existir antes de la rafaga (si no, la
    # serializa el unico parcial del telefono y no el lock): una reserva que
    # el panel cancela deja la ficha sin turnos futuros activos.
    previa = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff_ids[0], slot, "tope-rafaga-previa"),
    )
    assert previa.status_code == 201, previa.text
    cancelada = await client.patch(
        f"/appointments/{previa.json()['public_id']}/cancel",
        headers=auth_headers(token),
    )
    assert cancelada.status_code == 200, cancelada.text

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/public/appointments",
                json=_reserva(store, service, staff, slot, f"tope-rafaga-{i:02d}"),
            )
            for i, staff in enumerate(staff_ids)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), [r.text[:160] for r in respuestas]
    assert codigos.count(201) == MAX_FUTURE_BOOKINGS_PER_PHONE, codigos
    rechazos = [r.json()["error_code"] for r in respuestas if r.status_code != 201]
    assert rechazos == ["TOO_MANY_FUTURE_BOOKINGS"] * (
        PROFESIONALES - MAX_FUTURE_BOOKINGS_PER_PHONE
    ), rechazos
    assert (
        await _turnos_futuros_del_telefono(owner_engine, store)
        == MAX_FUTURE_BOOKINGS_PER_PHONE
    )
