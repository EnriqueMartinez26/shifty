"""El portal exige email para reservar y para anotarse en la lista de espera.

Decision de Mateo (2026-10-14). Sintoma: un cliente real de prueba reservo sin
email (el campo decia "Opcional") y despues no pudo entrar a "Mis turnos" a
ver ni cancelar su turno: el acceso es por un codigo que sale SOLO por email
("OTP solo por email"). La ficha quedaba con el email tecnico
``{tel}@store{id}.noreply``, que no recibe nada.

Lo mismo vale para la lista de espera publica: el cupo liberado solo se le
ofrece a quien tiene un email entregable (D-20260930-11), asi que anotarse sin
email no servia para nada.

Fuera de alcance: el alta del panel (``POST /appointments/``) y la reserva desde
la lista de espera por el personal siguen sin pedir email, porque la tienda
puede no tenerlo (``test_alta_del_panel_para_cliente.py``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.appointments.model import Appointment
from modules.waitlist.model import WaitlistEntry
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon

MENSAJE_RESERVA = (
    "Para reservar hace falta un email: ahí te enviamos la confirmación "
    "y el acceso a tus turnos."
)
MENSAJE_ESPERA = (
    "Para anotarte hace falta un email: ahí te avisamos si se libera un turno."
)


async def _tienda(client: AsyncClient, slug: str) -> tuple[str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return (
        store,
        service,
        staff,
        dia.replace(hour=13, minute=0, second=0, microsecond=0),
    )


def _reserva(
    store: str, service: str, staff: str, slot: datetime, **email: Any
) -> dict[str, Any]:
    return {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": "Agustina",
        "client_phone": "+5491155550142",
        "accepts_terms": True,
        "idempotency_key": "email-obligatorio-1",
        **email,
    }


async def _turnos(session: AsyncSession) -> int:
    session.expire_all()
    return int(
        (
            await session.execute(select(func.count()).select_from(Appointment))
        ).scalar_one()
    )


SIN_EMAIL: dict[str, dict[str, Any]] = {
    "ausente": {},
    "nulo": {"client_email": None},
    "vacio": {"client_email": ""},
    "espacios": {"client_email": "   "},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", sorted(SIN_EMAIL))
async def test_la_reserva_publica_sin_email_es_422_con_mensaje_claro(
    caso: str,
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, service, staff, slot = await _tienda(client, f"sin-email-{caso}")

    respuesta = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, **SIN_EMAIL[caso]),
    )

    assert respuesta.status_code == 422, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["message"] == MENSAJE_RESERVA
    assert await _turnos(test_session) == 0


@pytest.mark.asyncio
async def test_la_reserva_publica_con_un_email_invalido_es_422(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, service, staff, slot = await _tienda(client, "email-invalido")

    respuesta = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email="no-es-un-mail"),
    )

    assert respuesta.status_code == 422, respuesta.text
    assert "client_email" in respuesta.text
    assert await _turnos(test_session) == 0


@pytest.mark.asyncio
async def test_la_reserva_publica_con_email_se_crea(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, service, staff, slot = await _tienda(client, "con-email")

    respuesta = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email=" Agus@Example.COM "),
    )

    assert respuesta.status_code == 201, respuesta.text
    test_session.expire_all()
    turno = (await test_session.execute(select(Appointment))).scalar_one()
    # La ficha del cliente se normaliza aparte (test_email_publico_normalizado).
    assert (turno.client_email or "").lower() == "agus@example.com"


def _espera(store: str, service: str, slot: datetime, **email: Any) -> dict[str, Any]:
    return {
        "store_public_id": store,
        "service_id": service,
        "window_starts_at": slot.isoformat(),
        "window_ends_at": (slot + timedelta(hours=4)).isoformat(),
        "client_name": "Agustina",
        "client_phone": "+5491155550143",
        **email,
    }


async def _entradas(session: AsyncSession) -> int:
    session.expire_all()
    return int(
        (
            await session.execute(select(func.count()).select_from(WaitlistEntry))
        ).scalar_one()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", sorted(SIN_EMAIL))
async def test_anotarse_en_la_lista_de_espera_sin_email_es_422(
    caso: str,
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, service, _staff, slot = await _tienda(client, f"espera-sin-email-{caso}")

    respuesta = await client.post(
        "/public/waitlist", json=_espera(store, service, slot, **SIN_EMAIL[caso])
    )

    assert respuesta.status_code == 422, respuesta.text
    assert respuesta.json()["message"] == MENSAJE_ESPERA
    assert await _entradas(test_session) == 0


@pytest.mark.asyncio
async def test_anotarse_en_la_lista_de_espera_con_email_funciona(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, service, _staff, slot = await _tienda(client, "espera-con-email")

    respuesta = await client.post(
        "/public/waitlist",
        json=_espera(store, service, slot, client_email="agus@example.com"),
    )

    assert respuesta.status_code in (200, 201), respuesta.text
    assert await _entradas(test_session) == 1
