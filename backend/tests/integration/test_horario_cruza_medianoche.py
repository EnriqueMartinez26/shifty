"""La guarda de horario compara instantes, no la hora del dia suelta.

Auditoria 2, AUD2-B1-03 (2026-09-20). Sintoma:
``_staff_ids_with_schedule_for_slot`` comparaba ``time`` (hora del dia, sin
fecha) y exigia ``schedule.end_time >= end_time``. Un turno que termina
DESPUES de la medianoche local "daba la vuelta": para un turno de 23:30 local
de 60 minutos, ``end_time`` valia 00:30 y ``time(18, 0) >= time(0, 30)`` era
True, asi que la guarda se cumplia sola. Un POST directo a
``/public/appointments`` (anonimo, sin pasar por la grilla, que nunca ofrece
ese slot) agendaba a las 23:30 contra un horario de 09:00 a 18:00.

Es el unico chequeo de "el profesional atiende a esa hora" del alta publica:
comparar el rango real del dia local cierra el agujero sin tocar el camino
feliz.
"""

from __future__ import annotations

from typing import Any

from datetime import datetime, time, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.utils import ARGENTINA_TZ, local_to_utc
from modules.appointments.model import Appointment
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_staff,
    register_and_login,
)

TELEFONO = "+5491155550303"


async def _verificar_telefono(client: AsyncClient, store: str) -> None:
    pedido = await client.post(
        "/public/otp/request",
        json={"store_public_id": store, "phone": TELEFONO, "channel": "whatsapp"},
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store,
            "phone": TELEFONO,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text


async def _tienda_de_dia(client: AsyncClient, slug: str) -> tuple[str, str, str, str]:
    """Tienda con un servicio de 60 minutos y jornada local 09:00 a 18:00."""
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    servicio = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": "Consulta larga", "duration_minutes": 60, "price": 10000},
    )
    assert servicio.status_code == 201, servicio.text
    service = str(servicio.json()["public_id"])
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia_local = (datetime.now(ARGENTINA_TZ) + timedelta(days=5)).date()
    horario = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": dia_local.weekday(),
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    assert horario.status_code == 200, horario.text
    return store, token, service, staff


def _reserva(
    store: str, service: str, staff: str, inicio: datetime, clave: str
) -> dict[str, Any]:
    return {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": inicio.isoformat(),
        "client_name": "Trasnoche",
        # La autogestion exige una ficha con email ENTREGABLE verificado por
        # OTP (2026-09-20): sin email la ficha queda con el tecnico `.noreply`.
        "client_email": "trasnoche@example.com",
        "client_phone": "+5491155550303",
        "accepts_terms": True,
        "idempotency_key": clave,
    }


async def _turnos(session: AsyncSession) -> int:
    session.expire_all()
    return int(await session.scalar(select(func.count()).select_from(Appointment)) or 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("hora_local", [time(23, 30), time(23, 0)])
async def test_un_turno_que_cruza_la_medianoche_local_no_entra(
    client: AsyncClient, test_session: AsyncSession, hora_local: time
) -> None:
    """23:30 termina 00:30 del dia siguiente; 23:00 termina justo a medianoche."""
    slug = f"medianoche-{hora_local.hour}{hora_local.minute:02d}"
    store, _token, service, staff = await _tienda_de_dia(client, slug)
    dia_local = (datetime.now(ARGENTINA_TZ) + timedelta(days=5)).date()
    inicio = local_to_utc(dia_local, hora_local)
    antes = await _turnos(test_session)

    res = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, inicio, f"{slug}-0001"),
    )

    assert res.status_code == 409, res.text
    assert await _turnos(test_session) == antes


@pytest.mark.asyncio
async def test_reprogramar_tampoco_cruza_la_medianoche(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El mismo chequeo cubre la reprogramacion del cliente (mismo metodo).

    Aca el error si es explicito: ``staff_can_take_range`` traduce el rechazo
    a ``OUT_OF_SCHEDULE``.
    """
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    store, _token, service, staff = await _tienda_de_dia(client, "medianoche-repro")
    dia_local = (datetime.now(ARGENTINA_TZ) + timedelta(days=5)).date()
    original = await client.post(
        "/public/appointments",
        json=_reserva(
            store, service, staff, local_to_utc(dia_local, time(13, 0)), "repro-0001"
        ),
    )
    assert original.status_code == 201, original.text
    await _verificar_telefono(client, store)

    res = await client.patch(
        f"/public/client/appointments/{original.json()['public_id']}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": local_to_utc(dia_local, time(23, 30)).isoformat(),
            "idempotency_key": "repro-medianoche-01",
        },
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "OUT_OF_SCHEDULE"


@pytest.mark.asyncio
async def test_el_horario_de_siempre_sigue_entrando(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Regresion al reves: la jornada normal no se rompe por el arreglo."""
    store, _token, service, staff = await _tienda_de_dia(client, "medianoche-ok")
    dia_local = (datetime.now(ARGENTINA_TZ) + timedelta(days=5)).date()

    al_filo = await client.post(
        "/public/appointments",
        json=_reserva(
            store, service, staff, local_to_utc(dia_local, time(17, 0)), "ok-filo-01"
        ),
    )
    temprano = await client.post(
        "/public/appointments",
        json=_reserva(
            store, service, staff, local_to_utc(dia_local, time(9, 0)), "ok-abre-01"
        ),
    )

    # 17:00 a 18:00 es el ultimo turno que entra; 09:00 el primero.
    assert al_filo.status_code == 201, al_filo.text
    assert temprano.status_code == 201, temprano.text
    fuera = await client.post(
        "/public/appointments",
        json=_reserva(
            store, service, staff, local_to_utc(dia_local, time(17, 30)), "ok-fuera-01"
        ),
    )
    assert fuera.status_code == 409, fuera.text
