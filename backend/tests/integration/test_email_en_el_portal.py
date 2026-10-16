"""El email de la reserva publica: opcional, salvo con ``otp_booking``.

Propuesta por Mateo (2026-10-16), pendiente de OK del dueño; reemplaza el
email obligatorio de #181 (2026-10-14). Sintoma que motivo #181: un cliente
real de prueba reservo sin email y despues no pudo entrar a "Mis turnos" (el
acceso es por un codigo que sale SOLO por email). Exigirlo para todos frenaba
a quien no quiere dejarlo; ahora el front le dice que pierde y le da el
calendario y el WhatsApp de la tienda.

- Tienda SIN ``otp_booking``: sin email (ausente, nulo, vacio o en blanco) la
  reserva entra: un telefono nuevo crea la ficha con el tecnico
  ``{tel}@store{id}.noreply``, no se adopta el contacto de nadie y no se
  encola ningun mail. El turno guarda SIEMPRE el tecnico como email de esa
  reserva, aunque el telefono ya tenga una ficha con un email real: antes de
  #181 caia al email de la ficha y un telefono sin OTP le mandaba avisos al
  cliente real (revision de #191). La ficha no se toca.
- Tienda CON ``otp_booking``: el codigo sale solo por email, asi que sin email
  no hay forma de verificar. 422 ``CLIENT_EMAIL_REQUIRED`` con el mensaje de
  siempre, ANTES del gate de OTP (no un 403) y antes de escribir nada.
- Lista de espera publica: sigue exigiendo email, porque el cupo liberado solo
  se ofrece por email (D-20260930-11).

El alta del panel (``POST /appointments/``) nunca pidio email
(``test_alta_del_panel_para_cliente.py``).
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
from modules.users.model import User, UserRole
from modules.waitlist.model import WaitlistEntry
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon, usar_cola_de_reservas

MENSAJE_RESERVA = (
    "Para reservar hace falta un email: ahí te enviamos la confirmación "
    "y el acceso a tus turnos."
)
MENSAJE_ESPERA = (
    "Para anotarte hace falta un email: ahí te avisamos si se libera un turno."
)
TELEFONO = "5491155550142"


async def _tienda(
    client: AsyncClient, slug: str, *, otp_booking: bool = False
) -> tuple[str, str, str, datetime]:
    store, _token, service, staff, slot = await _tienda_con_token(
        client, slug, otp_booking=otp_booking
    )
    return store, service, staff, slot


async def _tienda_con_token(
    client: AsyncClient, slug: str, *, otp_booking: bool = False
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    if otp_booking:
        flags = await client.put(
            "/stores/me/feature-flags",
            headers=auth_headers(token),
            json={"otp_booking": True},
        )
        assert flags.status_code == 200, flags.text
    return (
        store,
        token,
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
        "client_phone": f"+{TELEFONO}",
        "accepts_terms": True,
        "idempotency_key": "email-en-el-portal-1",
        **email,
    }


async def _turnos(session: AsyncSession) -> int:
    session.expire_all()
    return int(
        (
            await session.execute(select(func.count()).select_from(Appointment))
        ).scalar_one()
    )


async def _ficha(session: AsyncSession) -> User:
    session.expire_all()
    return (
        await session.execute(
            select(User).where(User.phone == TELEFONO, User.role == UserRole.CLIENT)
        )
    ).scalar_one()


SIN_EMAIL: dict[str, dict[str, Any]] = {
    "ausente": {},
    "nulo": {"client_email": None},
    "vacio": {"client_email": ""},
    "espacios": {"client_email": "   "},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", sorted(SIN_EMAIL))
async def test_sin_otp_booking_la_reserva_sin_email_entra_con_la_ficha_tecnica(
    caso: str,
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    store, service, staff, slot = await _tienda(client, f"sin-email-{caso}")

    respuesta = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, **SIN_EMAIL[caso]),
    )

    assert respuesta.status_code == 201, respuesta.text
    assert await _turnos(test_session) == 1
    ficha = await _ficha(test_session)
    assert ficha.email == f"{TELEFONO}@store{ficha.store_id}.noreply".lower(), (
        "sin email la ficha nace con el tecnico .noreply, como antes de #181"
    )
    turno = (await test_session.execute(select(Appointment))).scalar_one()
    assert (turno.client_email or "").endswith(".noreply")
    assert cola.encolados == [], "un email tecnico no encola ningun mail"
    assert buzon.enviados == []


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", sorted(SIN_EMAIL))
async def test_con_otp_booking_la_reserva_sin_email_es_422_antes_del_gate(
    caso: str,
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin token de OTP a proposito: si el 422 no corriera antes del gate, la
    respuesta seria el 403 ``OTP_VERIFICATION_REQUIRED``."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, service, staff, slot = await _tienda(
        client, f"otp-sin-email-{caso}", otp_booking=True
    )

    respuesta = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, **SIN_EMAIL[caso]),
    )

    assert respuesta.status_code == 422, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["error_code"] == "CLIENT_EMAIL_REQUIRED"
    assert cuerpo["message"] == MENSAJE_RESERVA
    assert await _turnos(test_session) == 0
    test_session.expire_all()
    fichas = (
        await test_session.execute(
            select(func.count())
            .select_from(User)
            .where(User.phone == TELEFONO, User.role == UserRole.CLIENT)
        )
    ).scalar_one()
    assert fichas == 0, "el 422 corre antes de escribir nada"


@pytest.mark.asyncio
async def test_con_otp_booking_y_email_sin_verificar_sigue_el_403(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, service, staff, slot = await _tienda(
        client, "otp-con-email", otp_booking=True
    )

    respuesta = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, client_email="agus@example.com"),
    )

    assert respuesta.status_code == 403, respuesta.text
    assert respuesta.json()["error_code"] == "OTP_VERIFICATION_REQUIRED"
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
async def test_la_reserva_publica_con_email_se_crea_y_encola_el_aviso(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    cola = usar_cola_de_reservas(monkeypatch, test_session)
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
    assert len(cola.encolados) == 1


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
async def test_anotarse_en_la_lista_de_espera_sin_email_sigue_siendo_422(
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


# --- El panel sabe quien no recibe avisos por email -------------------------


@pytest.mark.asyncio
async def test_la_agenda_y_el_bloqueo_dicen_que_turno_no_tiene_email(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``client_has_email`` (aditivo): sin el, la agenda y el modal del bloqueo
    sugieren avisar por WhatsApp. Es un booleano: el email no se expone."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    usar_cola_de_reservas(monkeypatch, test_session)
    store, token, service, staff, slot = await _tienda_con_token(
        client, "panel-sin-email"
    )
    sin_email = await client.post(
        "/public/appointments", json=_reserva(store, service, staff, slot)
    )
    assert sin_email.status_code == 201, sin_email.text
    con_email = await client.post(
        "/public/appointments",
        json={
            **_reserva(store, service, staff, slot + timedelta(hours=1)),
            "client_phone": "+5491155550199",
            "client_email": "lucia@example.com",
            "idempotency_key": "email-en-el-portal-2",
        },
    )
    assert con_email.status_code == 201, con_email.text
    esperado = {
        sin_email.json()["public_id"]: False,
        con_email.json()["public_id"]: True,
    }

    busqueda = await client.get(
        "/appointments/search?page=1&page_size=10", headers=auth_headers(token)
    )
    assert busqueda.status_code == 200, busqueda.text
    assert {
        item["public_id"]: item["client_has_email"]
        for item in busqueda.json()["results"]
    } == esperado
    assert "lucia@example.com" not in busqueda.text

    preview = await client.post(
        "/appointment-blocks/preview",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "ends_at": (slot + timedelta(hours=2)).isoformat(),
        },
    )
    assert preview.status_code == 200, preview.text
    assert {
        item["public_id"]: item["client_has_email"]
        for item in preview.json()["affected"]
    } == esperado


# --- Sin email, el turno nunca toma el email de una ficha existente ---------


async def _primera_reserva_con_email(
    client: AsyncClient, store: str, service: str, staff: str, slot: datetime
) -> None:
    primera = await client.post(
        "/public/appointments",
        json={
            **_reserva(store, service, staff, slot),
            "client_email": "duenia@example.com",
            "idempotency_key": "email-en-el-portal-ficha-1",
        },
    )
    assert primera.status_code == 201, primera.text


@pytest.mark.asyncio
async def test_sin_email_no_avisa_al_email_de_la_ficha_del_telefono(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revision de #191 (2026-10-16): un telefono sin OTP no es de nadie.

    El telefono ya tiene una ficha con email real. Una reserva SIN email con
    ese telefono la puede hacer cualquiera: si el turno tomara el email de la
    ficha, "reserva registrada", la confirmacion y los recordatorios le
    llegarian al cliente real. El turno guarda el tecnico ``.noreply``, no se
    encola nada, la ficha no cambia y el panel ve ``client_has_email=false``.
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    store, token, service, staff, slot = await _tienda_con_token(
        client, "ficha-sin-email"
    )
    await _primera_reserva_con_email(client, store, service, staff, slot)
    cola.encolados.clear()

    segunda = await client.post(
        "/public/appointments",
        json={
            **_reserva(store, service, staff, slot + timedelta(hours=1)),
            "client_name": "Otra persona",
            "idempotency_key": "email-en-el-portal-ficha-2",
        },
    )

    assert segunda.status_code == 201, segunda.text
    assert cola.encolados == [], "sin email no se avisa al email de la ficha"
    test_session.expire_all()
    turno = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == segunda.json()["public_id"])
        )
    ).scalar_one()
    assert (turno.client_email or "").endswith(".noreply")
    assert turno.client_email != "duenia@example.com"
    assert (await _ficha(test_session)).email == "duenia@example.com"

    busqueda = await client.get(
        "/appointments/search?page=1&page_size=10", headers=auth_headers(token)
    )
    assert busqueda.status_code == 200, busqueda.text
    banderas = {
        item["public_id"]: item["client_has_email"]
        for item in busqueda.json()["results"]
    }
    assert banderas[segunda.json()["public_id"]] is False


@pytest.mark.asyncio
async def test_con_email_tipeado_sobre_una_ficha_existente_avisa_a_ese_email(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lo de siempre: el mail de ESTA reserva va al email que dejaron, sin
    pisar el de la ficha (``test_secuestro_de_contacto.py``)."""
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    store, _token, service, staff, slot = await _tienda_con_token(
        client, "ficha-con-email"
    )
    await _primera_reserva_con_email(client, store, service, staff, slot)
    cola.encolados.clear()

    segunda = await client.post(
        "/public/appointments",
        json={
            **_reserva(store, service, staff, slot + timedelta(hours=1)),
            "client_email": "otra@example.com",
            "idempotency_key": "email-en-el-portal-ficha-3",
        },
    )

    assert segunda.status_code == 201, segunda.text
    test_session.expire_all()
    turno = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == segunda.json()["public_id"])
        )
    ).scalar_one()
    assert turno.client_email == "otra@example.com"
    assert (await _ficha(test_session)).email == "duenia@example.com"
    assert len(cola.encolados) == 1
    await cola.entregar()
    assert [destino for destino, _a, _c in buzon.enviados] == ["otra@example.com"]
