"""FF-04: "Nuevo turno" del panel reserva para un cliente por el panel.

2026-09-24. Sintoma (revision-funcional-front.md, FF-04): el boton "Nuevo
turno" del panel reservaba por ``POST /public/appointments`` y heredaba las
reglas del portal anonimo: antelacion minima (el dueno no podia cargar a quien
esta en el local "ahora"), campos extra obligatorios, sena obligatoria (422),
el rate limit publico y el 404 de tienda suspendida en vez del 402 del panel.

Contrato (aditivo): ``POST /appointments/`` acepta ``client_name`` +
``client_phone`` (+ ``client_email``, ``allow_outside_schedule``). Con esos
datos el turno es PARA ESE CLIENTE: sin antelacion minima (no mas de 5 minutos
en el pasado), sin OTP ni campos extra, sin sena (nace CONFIRMED y sin cobro),
con horario del profesional (fuera de horario solo un admin con
``allow_outside_schedule``), bloqueos, choques y buffer. Sin esos datos el
endpoint sigue siendo el auto-turno de siempre.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.appointments.service as appointments_service
from core.availability_cache import invalidate_availability
from core.security import hash_password
from modules.appointments.model import Appointment
from modules.notifications.tasks import EVENT_APPOINTMENT_BOOKED_BY_PANEL
from modules.payments.model import OutboxMessage, Payment
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_suspension_por_endpoint import _suspender

PASSWORD = "Password123!"


class Agenda:
    def __init__(
        self, store: str, token: str, service: str, staff: str, slot: datetime
    ) -> None:
        self.store = store
        self.token = token
        self.service = service
        self.staff = staff
        self.slot = slot


async def _agenda(client: AsyncClient, slug: str, **servicio: Any) -> Agenda:
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    service = await create_service(client, token, **servicio)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    # 11:00 UTC = 08:00 local, dentro de la jornada de 06 a 18 local.
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)
    return Agenda(store, token, service, staff, slot)


def _cuerpo(agenda: Agenda, **extra: Any) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {
        "service_id": agenda.service,
        "staff_id": agenda.staff,
        "starts_at": agenda.slot.isoformat(),
        "client_name": "Walk In",
        "client_phone": "+54 9 11 5555-0101",
        "idempotency_key": f"ff04-{agenda.slot.isoformat()}",
    }
    cuerpo.update(extra)
    return {k: v for k, v in cuerpo.items() if v is not None}


async def _reservar(
    client: AsyncClient, agenda: Agenda, token: str | None = None, **extra: Any
) -> Any:
    return await client.post(
        "/appointments/",
        headers=auth_headers(token or agenda.token),
        json=_cuerpo(agenda, **extra),
    )


async def _usuario(
    client: AsyncClient,
    session: AsyncSession,
    agenda: Agenda,
    *,
    email: str,
    role: str,
    user_id: str | None = None,
) -> str:
    """Usuario del personal con clave, logueado; devuelve el token."""
    store_id = (
        await session.execute(select(Store.id).where(Store.public_id == agenda.store))
    ).scalar_one()
    if user_id is not None:
        # El profesional que crea /staff/ nace sin clave usable: se la damos.
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(hashed_password=hash_password(PASSWORD))
        )
    else:
        session.add(
            User(
                email=email,
                hashed_password=hash_password(PASSWORD),
                first_name="Otro",
                last_name="Rol",
                role=role,
                store_id=store_id,
            )
        )
    await session.commit()
    login = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


async def _turno(session: AsyncSession, public_id: str) -> Appointment:
    return (
        await session.execute(select(Appointment).where(Appointment.id == public_id))
    ).scalar_one()


@pytest.mark.asyncio
async def test_el_admin_reserva_para_un_cliente_nuevo_confirmado_y_sin_cobro(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    # Sena obligatoria configurada: el panel nunca la fuerza.
    agenda = await _agenda(
        client, "ff04-alta", deposit_mode="required", deposit_amount=50
    )
    # Campos extra obligatorios: el portal los exige, el panel no.
    campos = await client.patch(
        "/stores/me",
        headers=auth_headers(agenda.token),
        json={
            "custom_client_fields": [
                {"key": "dni", "label": "DNI", "type": "text", "required": True}
            ]
        },
    )
    assert campos.status_code == 200, campos.text

    res = await _reservar(
        client, agenda, client_email="Walk.In@Example.com", notes="Pasa sin turno"
    )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "confirmed"
    assert body["staff_id"] == agenda.staff
    assert body["service_id"] == agenda.service
    assert body["notes"] == "Pasa sin turno"
    turno = await _turno(test_session, body["public_id"])
    assert turno.client_name == "Walk In"
    assert turno.client_email == "walk.in@example.com"
    assert turno.price_amount == Decimal("10000")
    assert turno.expires_at is None
    cliente = (
        await test_session.execute(select(User).where(User.id == turno.client_id))
    ).scalar_one()
    assert cliente.role == UserRole.CLIENT.value
    assert cliente.phone == "5491155550101"
    assert cliente.store_id == turno.store_id
    pagos = (await test_session.execute(select(Payment))).scalars().all()
    assert pagos == []


@pytest.mark.asyncio
async def test_sin_antelacion_minima_y_con_turnos_ya_pasados(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Decision del dueno (2026-09-25): la TIENDA puede cargar un horario que
    ya paso (un walk-in que se registra despues), hasta el piso contra el
    desborde (2 anios). Sin mail de "turno confirmado" para un turno que ya
    empezo; el cliente final nunca reserva en el pasado."""
    agenda = await _agenda(client, "ff04-ahora")
    ahora = datetime.now(timezone.utc)

    # Hace tres horas, con email entregable. Fuera de horario a proposito
    # (admin): la hora a la que corre el test no se controla.
    pasado = await _reservar(
        client,
        agenda,
        starts_at=(ahora - timedelta(hours=3)).isoformat(),
        client_email="walkin@example.com",
        allow_outside_schedule=True,
        idempotency_key="ff04-ahora-1",
    )
    assert pasado.status_code == 201, pasado.text

    # En una hora: el portal exige 2 h de antelacion (default de la tienda).
    en_un_rato = await _reservar(
        client,
        agenda,
        starts_at=(ahora + timedelta(hours=1)).isoformat(),
        allow_outside_schedule=True,
        idempotency_key="ff04-ahora-2",
    )
    assert en_un_rato.status_code == 201, en_un_rato.text

    muy_viejo = await _reservar(
        client,
        agenda,
        starts_at=(ahora - timedelta(days=731)).isoformat(),
        allow_outside_schedule=True,
        idempotency_key="ff04-ahora-4",
    )
    assert muy_viejo.status_code == 422, muy_viejo.text

    avisos = (
        (
            await test_session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == EVENT_APPOINTMENT_BOOKED_BY_PANEL
                )
            )
        )
        .scalars()
        .all()
    )
    # Solo el turno futuro (la ficha quedo con el email del walk-in) lleva
    # aviso; el que ya paso, no.
    assert [a.payload["appointment_id"] for a in avisos] == [
        en_un_rato.json()["public_id"]
    ]


@pytest.mark.asyncio
async def test_reusa_el_cliente_de_la_tienda_y_no_toca_el_de_otra(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    ajena = await _agenda(client, "ff04-ajena")
    agenda = await _agenda(client, "ff04-reusa")
    telefono = "+5491155550303"
    # El mismo telefono ya es cliente de OTRA tienda.
    otra = await _reservar(
        client, ajena, client_phone=telefono, idempotency_key="ff04-ajena-1"
    )
    assert otra.status_code == 201, otra.text
    cliente_ajeno = (await _turno(test_session, otra.json()["public_id"])).client_id

    primera = await _reservar(client, agenda, client_phone=telefono)
    assert primera.status_code == 201, primera.text
    segunda = await _reservar(
        client,
        agenda,
        client_phone=telefono,
        client_name="Otro Nombre",
        starts_at=(agenda.slot + timedelta(hours=1)).isoformat(),
        idempotency_key="ff04-reusa-2",
    )
    assert segunda.status_code == 201, segunda.text

    uno = await _turno(test_session, primera.json()["public_id"])
    dos = await _turno(test_session, segunda.json()["public_id"])
    assert uno.client_id == dos.client_id
    assert uno.client_id != cliente_ajeno
    ficha = (
        await test_session.execute(select(User).where(User.id == uno.client_id))
    ).scalar_one()
    # La ficha existente no se pisa (nombre de la primera alta).
    assert ficha.full_name == "Walk In"


@pytest.mark.asyncio
async def test_sin_profesional_elige_uno_que_atiende(client: AsyncClient) -> None:
    agenda = await _agenda(client, "ff04-auto")

    res = await _reservar(client, agenda, staff_id=None)

    assert res.status_code == 201, res.text
    assert res.json()["staff_id"] == agenda.staff


@pytest.mark.asyncio
async def test_fuera_de_horario_409_y_el_admin_puede_forzarlo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    agenda = await _agenda(client, "ff04-horario")
    # 23:00 UTC = 20:00 local: la jornada cierra a las 18 local.
    tarde = agenda.slot.replace(hour=23).isoformat()

    fuera = await _reservar(client, agenda, starts_at=tarde)
    assert fuera.status_code == 409, fuera.text
    assert fuera.json()["error_code"] == "OUT_OF_SCHEDULE"

    sin_profesional = await _reservar(
        client, agenda, starts_at=tarde, staff_id=None, idempotency_key="ff04-horario-2"
    )
    assert sin_profesional.status_code == 409, sin_profesional.text
    assert sin_profesional.json()["error_code"] == "NO_STAFF_AVAILABLE"

    recepcion = await _usuario(
        client, test_session, agenda, email="recepcion-ff04@t.com", role="receptionist"
    )
    prohibido = await _reservar(
        client,
        agenda,
        token=recepcion,
        starts_at=tarde,
        allow_outside_schedule=True,
        idempotency_key="ff04-horario-3",
    )
    assert prohibido.status_code == 403, prohibido.text

    forzado = await _reservar(
        client,
        agenda,
        starts_at=tarde,
        allow_outside_schedule=True,
        idempotency_key="ff04-horario-4",
    )
    assert forzado.status_code == 201, forzado.text


@pytest.mark.asyncio
async def test_respeta_bloqueos_choques_y_buffer(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    agenda = await _agenda(client, "ff04-choques")
    await test_session.execute(
        update(Store).where(Store.public_id == agenda.store).values(buffer_minutes=15)
    )
    await test_session.commit()
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(agenda.token),
        json={
            "staff_id": agenda.staff,
            "starts_at": (agenda.slot + timedelta(hours=3)).isoformat(),
            "ends_at": (agenda.slot + timedelta(hours=4)).isoformat(),
            "reason": "Tramite",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text

    primero = await _reservar(client, agenda)
    assert primero.status_code == 201, primero.text

    choque = await _reservar(
        client,
        agenda,
        client_phone="+5491155550404",
        idempotency_key="ff04-choque-2",
    )
    assert choque.status_code == 409, choque.text
    assert choque.json()["error_code"] == "APPOINTMENT_CONFLICT"

    # Termina 11:30; a las 11:40 queda dentro del buffer de 15 minutos.
    buffer = await _reservar(
        client,
        agenda,
        client_phone="+5491155550405",
        starts_at=(agenda.slot + timedelta(minutes=40)).isoformat(),
        idempotency_key="ff04-choque-3",
    )
    assert buffer.status_code == 409, buffer.text

    # El bloqueo manda aunque el admin fuerce el horario.
    bloqueado = await _reservar(
        client,
        agenda,
        client_phone="+5491155550406",
        starts_at=(agenda.slot + timedelta(hours=3)).isoformat(),
        allow_outside_schedule=True,
        idempotency_key="ff04-choque-4",
    )
    assert bloqueado.status_code == 409, bloqueado.text
    assert bloqueado.json()["error_code"] == "SCHEDULE_BLOCKED"


@pytest.mark.asyncio
async def test_el_profesional_reserva_solo_en_su_agenda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    agenda = await _agenda(client, "ff04-pro")
    otro = await create_staff(
        client, agenda.token, agenda.service, email="otro-ff04@t.com"
    )
    await add_staff_schedule(client, agenda.token, otro, target_date=agenda.slot)
    token = await _usuario(
        client,
        test_session,
        agenda,
        email="pro-ff04-pro@t.com",
        role="staff",
        user_id=agenda.staff,
    )

    ajeno = await _reservar(client, agenda, token=token, staff_id=otro)
    assert ajeno.status_code == 403, ajeno.text

    propio = await _reservar(
        client, agenda, token=token, staff_id=None, idempotency_key="ff04-pro-2"
    )
    assert propio.status_code == 201, propio.text
    assert propio.json()["staff_id"] == agenda.staff


@pytest.mark.asyncio
async def test_la_recepcion_reserva_para_un_cliente(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    agenda = await _agenda(client, "ff04-recep")
    token = await _usuario(
        client, test_session, agenda, email="recep-ff04@t.com", role="receptionist"
    )

    res = await _reservar(client, agenda, token=token)

    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_texto_con_caracteres_de_control_422(client: AsyncClient) -> None:
    agenda = await _agenda(client, "ff04-hostil")

    nombre = await _reservar(client, agenda, client_name="Walk‮In")
    notas = await _reservar(client, agenda, notes="hola\x00")

    assert nombre.status_code == 422, nombre.text
    assert notas.status_code == 422, notas.text


@pytest.mark.asyncio
async def test_datos_del_cliente_incompletos_422(client: AsyncClient) -> None:
    agenda = await _agenda(client, "ff04-incompleto")

    sin_telefono = await _reservar(client, agenda, client_phone=None)
    sin_nombre = await _reservar(client, agenda, client_name=None)
    forzar_sin_cliente = await client.post(
        "/appointments/",
        headers=auth_headers(agenda.token),
        json={
            "service_id": agenda.service,
            "staff_id": agenda.staff,
            "starts_at": agenda.slot.isoformat(),
            "allow_outside_schedule": True,
            "idempotency_key": "ff04-incompleto-3",
        },
    )

    assert sin_telefono.status_code == 422, sin_telefono.text
    assert sin_nombre.status_code == 422, sin_nombre.text
    assert forzar_sin_cliente.status_code == 422, forzar_sin_cliente.text


@pytest.mark.asyncio
async def test_misma_clave_devuelve_el_mismo_turno(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    agenda = await _agenda(client, "ff04-idem")

    uno = await _reservar(client, agenda)
    dos = await _reservar(client, agenda)

    assert uno.status_code == dos.status_code == 201, (uno.text, dos.text)
    assert uno.json()["public_id"] == dos.json()["public_id"]
    turnos = (await test_session.execute(select(Appointment))).scalars().all()
    assert len(turnos) == 1


@pytest.mark.asyncio
async def test_tienda_suspendida_402(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    agenda = await _agenda(client, "ff04-suspendida")
    await _suspender(test_session, agenda.store)

    res = await _reservar(client, agenda)

    assert res.status_code == 402, res.text
    assert res.json()["error_code"] == "SUBSCRIPTION_SUSPENDED"


@pytest.mark.asyncio
async def test_aviso_por_outbox_solo_con_email_entregable_e_invalida_despues(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agenda = await _agenda(client, "ff04-aviso")
    invalidaciones: list[datetime] = []

    async def invalidar(cache: Any, store_id: str, *dias: datetime) -> None:
        invalidaciones.extend(dias)
        await invalidate_availability(cache, store_id, *dias)

    monkeypatch.setattr(appointments_service, "invalidate_availability", invalidar)

    con_email = await _reservar(client, agenda, client_email="cliente@example.com")
    sin_email = await _reservar(
        client,
        agenda,
        client_phone="+5491155550505",
        starts_at=(agenda.slot + timedelta(hours=1)).isoformat(),
        idempotency_key="ff04-aviso-2",
    )
    assert con_email.status_code == sin_email.status_code == 201

    eventos = (
        (
            await test_session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == EVENT_APPOINTMENT_BOOKED_BY_PANEL
                )
            )
        )
        .scalars()
        .all()
    )
    assert [e.payload["appointment_id"] for e in eventos] == [
        con_email.json()["public_id"]
    ]
    assert len(invalidaciones) == 2


@pytest.mark.asyncio
async def test_el_panel_no_pide_consentimiento_y_el_portal_si(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Desde 0fd204f el portal exige ``accepts_terms`` (PV-09) y el "Nuevo
    turno" del panel, que reservaba por el portal sin mandarlo, daba 422. El
    personal no es el cliente dando su consentimiento: el alta del panel no lo
    pide y deja ``terms_accepted_at`` en NULL. El portal lo sigue exigiendo.
    """
    agenda = await _agenda(client, "ff04-terminos")

    panel = await _reservar(client, agenda)
    portal = await client.post(
        "/public/appointments",
        json={
            "store_public_id": agenda.store,
            "service_id": agenda.service,
            "staff_id": agenda.staff,
            "starts_at": (agenda.slot + timedelta(hours=2)).isoformat(),
            "client_name": "Sin Terminos",
            "client_phone": "+5491155550606",
            "idempotency_key": "ff04-terminos-portal",
        },
    )

    assert panel.status_code == 201, panel.text
    assert (
        await _turno(test_session, panel.json()["public_id"])
    ).terms_accepted_at is None
    assert portal.status_code == 422, portal.text


@pytest.mark.asyncio
async def test_inicio_lejano_422_y_no_500(client: AsyncClient) -> None:
    """Revision de perf/f4-back: ``starts_at`` = 9999-12-31 daba 500
    (``starts_at + duracion`` levanta ``OverflowError``) en las dos formas.
    Tope de las dos formas: 2 anios (``MAX_BOOKING_AHEAD``). El alta para un
    cliente reemplaza al "Nuevo turno" que hoy reserva por el portal con fecha
    libre; acotarla a 120 dias seria un cambio de producto (revision de
    perf/f4-back)."""
    agenda = await _agenda(client, "ff04-lejano")
    ahora = datetime.now(timezone.utc)
    lejano = "9999-12-31T23:59:00+00:00"

    cliente_lejano = await _reservar(client, agenda, starts_at=lejano)
    cliente_731 = await _reservar(
        client,
        agenda,
        starts_at=(ahora + timedelta(days=731)).isoformat(),
        allow_outside_schedule=True,
        idempotency_key="ff04-lejano-731",
    )
    cliente_400 = await _reservar(
        client,
        agenda,
        # Un dia despues del auto-turno de 400 dias (mismo profesional).
        starts_at=(ahora + timedelta(days=401)).isoformat(),
        allow_outside_schedule=True,
        idempotency_key="ff04-lejano-400",
    )

    def auto(cuando: str, clave: str) -> dict[str, Any]:
        return {
            "service_id": agenda.service,
            "staff_id": agenda.staff,
            "starts_at": cuando,
            "idempotency_key": clave,
        }

    headers = auth_headers(agenda.token)
    auto_lejano = await client.post(
        "/appointments/", headers=headers, json=auto(lejano, "ff04-auto-lejano")
    )
    auto_731 = await client.post(
        "/appointments/",
        headers=headers,
        json=auto((ahora + timedelta(days=731)).isoformat(), "ff04-auto-731"),
    )
    auto_400 = await client.post(
        "/appointments/",
        headers=headers,
        json=auto((ahora + timedelta(days=400)).isoformat(), "ff04-auto-400"),
    )

    for res in (cliente_lejano, cliente_731, auto_lejano, auto_731):
        assert res.status_code == 422, res.text
    assert cliente_400.status_code == 201, cliente_400.text
    assert auto_400.status_code == 201, auto_400.text


@pytest.mark.asyncio
async def test_email_de_otra_tienda_entra_y_el_de_la_misma_tienda_es_409_neutro(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """PV-01 (2026-09-25, decision del dueno): el email de un cliente es unico
    POR TIENDA. Hasta ese dia era unico global y un cliente nuevo con el email
    de un usuario de otra tienda chocaba (409): el mismo cliente no podia
    reservar en dos tiendas y el 409 confirmaba que el email existia. Ahora
    entra. Dentro de la tienda, un telefono nuevo con el email de otro cliente
    sigue siendo el 409 neutro de siempre, sin nombrar nada."""
    ajena = await _agenda(client, "ff04-email-ajena")
    agenda = await _agenda(client, "ff04-email")
    primera = await _reservar(
        client,
        ajena,
        client_email="compartido@example.com",
        idempotency_key="ff04-email-ajena-1",
    )
    assert primera.status_code == 201, primera.text

    otra_tienda = await _reservar(
        client,
        agenda,
        client_phone="+5491155550707",
        client_email="Compartido@Example.com",
        idempotency_key="ff04-email-1",
    )
    assert otra_tienda.status_code == 201, otra_tienda.text

    res = await _reservar(
        client,
        agenda,
        client_phone="+5491155550708",
        client_email="compartido@example.com",
        starts_at=(agenda.slot + timedelta(hours=1)).isoformat(),
        idempotency_key="ff04-email-2",
    )
    assert res.status_code == 409, res.text
    cuerpo = res.json()
    assert cuerpo["error_code"] == "RESOURCE_CONFLICT"
    texto = res.text.lower()
    for dato in ("ff04-email", "tienda ff04", "compartido", agenda.store.lower()):
        assert dato not in texto, (dato, res.text)
    turnos = (await test_session.execute(select(Appointment))).scalars().all()
    assert len(turnos) == 2
