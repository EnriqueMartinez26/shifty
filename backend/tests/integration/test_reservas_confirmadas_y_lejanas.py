"""Reserva publica sin cobro confirmada y reserva lejana por Mercado Pago.

Decisiones de Mateo (2026-10-20):

A) Una reserva publica que no cobra nada (sin sena, sena opcional sin MP
   elegido, o sena obligatoria de importe cero) nace ``confirmed`` y sin
   ``expires_at``. Antes nacia ``pending`` retenida hasta su inicio: el job de
   expiracion la levantaba a esa hora si nadie la confirmaba, el cliente
   recibia "reserva registrada" y el dueno un aviso que decia "Confirmalo
   cuando recibas la transferencia" de una reserva que no tenia nada que
   pagar. Ahora el cliente recibe "turno confirmado" y el dueno un aviso
   informativo ("Nueva reserva"). La sena por WhatsApp no cambia.

B) Un turno que empieza a mas de 30 dias locales y pide sena obligatoria se
   cobra SOLO por Mercado Pago: WhatsApp es 422
   ``FAR_BOOKING_REQUIRES_MERCADOPAGO`` y una tienda sin MP usable no lo toma
   (422 ``FAR_BOOKING_UNAVAILABLE``), siempre antes de escribir nada. Tampoco
   se muda una sena por WhatsApp a una fecha lejana desde "Mis turnos". Un
   servicio sin sena obligatoria no cambia, y la grilla publica no ofrece el
   dia lejano que el alta rechazaria.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from core.utils import ensure_utc_aware
from modules.appointments.model import Appointment, AppointmentStatus
from modules.appointments.repository import AppointmentRepository
from modules.notifications.model import Notification, NotificationType
from modules.notifications.tasks import (
    BOOKING_MAIL_CONFIRMATION,
    BOOKING_MAIL_REGISTRATION,
)
from modules.payments.deposit_channels import FAR_BOOKING_DAYS
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import OutboxMessage, Payment
from modules.services.model import Service
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon, usar_cola_de_reservas
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
    _stub_preference,
)
from tests.integration.test_sena_por_mp_o_whatsapp import (
    _cobro,
    _eventos,
    _mp_prohibido,
    _reservar,
    _Tienda,
    _tienda,
    _turno,
    _whatsapp,
)
from tests.integration.test_sena_por_whatsapp_regla_3 import (
    TELEFONO,
    _verificar_cliente,
)

# El ``_tienda`` de la sena reserva a 4 dias; 6 semanas despues cae el mismo
# dia de la semana (el horario del profesional es semanal) y a 46 dias: lejano.
SEMANAS_LEJOS = timedelta(weeks=6)


def _lejos(t: _Tienda) -> _Tienda:
    assert (t.dia + SEMANAS_LEJOS - datetime.now(timezone.utc)).days > FAR_BOOKING_DAYS
    return _Tienda(t.store, t.token, t.servicio, t.staff, t.dia + SEMANAS_LEJOS)


async def _tienda_sin_sena(client: AsyncClient, slug: str, **servicio: Any) -> _Tienda:
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    service = await create_service(client, token, **servicio)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return _Tienda(store, token, service, staff, dia)


async def _cuantos(session: AsyncSession, modelo: Any, *filtros: Any) -> int:
    session.expire_all()
    return int(
        await session.scalar(select(func.count()).select_from(modelo).where(*filtros))
        or 0
    )


async def _nada_escrito(session: AsyncSession, eventos_antes: int) -> None:
    """El rechazo fue antes de escribir: ni turno, ni cobro, ni ficha del
    cliente, ni eventos nuevos en el outbox."""
    assert await _cuantos(session, Appointment) == 0
    assert await _cuantos(session, Payment) == 0
    assert await _cuantos(session, User, User.role == UserRole.CLIENT) == 0
    assert await _cuantos(session, OutboxMessage) == eventos_antes


# ---------------------------------------------------------------------------
# A) Sin cobro nace confirmada
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reserva_sin_sena_nace_confirmada_con_sus_avisos(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    t = await _tienda_sin_sena(client, "a-sin-sena")

    res = await _reservar(client, t, metodo="auto")

    assert res.status_code == 201, res.text
    cuerpo = res.json()
    assert cuerpo["status"] == AppointmentStatus.CONFIRMED.value
    assert cuerpo["payment_required"] is False
    assert cuerpo["deposit_channel"] is None
    assert cuerpo["deposit_deadline"] is None
    assert cuerpo["payment_link"] is None
    turno = await _turno(test_session, cuerpo["public_id"])
    assert turno.status == AppointmentStatus.CONFIRMED.value
    assert turno.expires_at is None  # sin retencion que vencer
    # Leidos ahora: cada consulta de abajo expira la sesion.
    turno_id, inicio = turno.id, ensure_utc_aware(turno.starts_at)
    assert await _cobro(test_session, turno_id) is None

    # Cliente: "turno confirmado", no "reserva registrada".
    assert [a[0] for a in cola.encolados] == [BOOKING_MAIL_CONFIRMATION]
    assert BOOKING_MAIL_REGISTRATION not in [a[0] for a in cola.encolados]

    # Dueno: un aviso informativo, ninguno de "pendiente de confirmar".
    assert (
        await _eventos(
            test_session, NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value
        )
        == []
    )
    avisos = await _eventos(
        test_session, NotificationType.APPOINTMENT_BOOKED_ONLINE.value
    )
    assert [a.payload["appointment_id"] for a in avisos] == [turno_id]
    assert avisos[0].payload["client_name"] == "Cliente Sena"

    await process_outbox_batch(test_session, limit=50)
    test_session.expire_all()
    notificacion = (
        await test_session.execute(
            select(Notification).where(Notification.appointment_id == turno_id)
        )
    ).scalar_one()
    assert notificacion.type == NotificationType.APPOINTMENT_BOOKED_ONLINE.value
    assert notificacion.title == "Nueva reserva"
    assert "Cliente Sena reservó Consulta para el" in (notificacion.body or "")
    assert "confirmado" in (notificacion.body or "")
    assert "transferencia" not in (notificacion.body or "")
    assert "Confirmalo" not in (notificacion.body or "")
    # La replica por mail al admin lleva el mismo texto.
    al_dueno = [m for m in buzon.enviados if m[0] == "a-sin-sena@t.com"]
    assert [m[1] for m in al_dueno] == ["Shifty - Nueva reserva"]

    # El worker manda la confirmacion: el turno sigue confirmado.
    assert await cola.entregar() == [{"status": "sent"}]

    # Recordatorios: el turno confirmado entra en su ventana.
    candidatos = await AppointmentRepository(test_session).get_upcoming_for_reminders(
        inicio - timedelta(hours=1),
        inicio + timedelta(hours=1),
        pending_column="reminder_24h_sent_at",
    )
    assert [fila[0].id for fila in candidatos] == [turno_id]


@pytest.mark.asyncio
async def test_sena_opcional_sin_mp_elegido_nace_confirmada(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    cola = usar_cola_de_reservas(monkeypatch, test_session)
    t = await _tienda_sin_sena(
        client,
        "a-opcional",
        deposit_mode="optional",
        deposit_type="percent",
        deposit_amount=30,
    )

    res = await _reservar(client, t, metodo="manual")

    assert res.status_code == 201, res.text
    assert res.json()["status"] == AppointmentStatus.CONFIRMED.value
    assert res.json()["payment_required"] is False
    turno = await _turno(test_session, res.json()["public_id"])
    assert (turno.status, turno.expires_at) == ("confirmed", None)
    assert await _cobro(test_session, res.json()["public_id"]) is None
    assert [a[0] for a in cola.encolados] == [BOOKING_MAIL_CONFIRMATION]


@pytest.mark.asyncio
async def test_sena_obligatoria_de_importe_cero_nace_confirmada(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    usar_cola_de_reservas(monkeypatch, test_session)
    store, token = await register_and_login(
        client, slug="a-sena-cero", email="a-sena-cero@t.com"
    )
    await _whatsapp(client, token, "11 5555 0303")
    servicio = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    # El panel no deja una sena de cero: la da un precio cero (30 % de 0).
    await test_session.execute(
        update(Service).where(Service.public_id == servicio).values(price=0)
    )
    await test_session.commit()
    staff = await create_staff(client, token, servicio, email="pro-a-sena-cero@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff, target_date=dia)

    res = await _reservar(
        client, _Tienda(store, token, servicio, staff, dia), metodo="manual"
    )

    assert res.status_code == 201, res.text
    assert res.json()["status"] == AppointmentStatus.CONFIRMED.value
    assert await _cobro(test_session, res.json()["public_id"]) is None


@pytest.mark.asyncio
async def test_la_sena_por_whatsapp_sigue_pendiente_con_su_aviso(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "a-whatsapp-igual")

    res = await _reservar(client, t, metodo="manual")

    assert res.status_code == 201, res.text
    assert res.json()["status"] == AppointmentStatus.PENDING_PAYMENT.value
    assert res.json()["deposit_channel"] == "whatsapp"
    avisos = await _eventos(
        test_session, NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value
    )
    assert [a.payload["channel"] for a in avisos] == ["whatsapp"]
    assert (
        await _eventos(test_session, NotificationType.APPOINTMENT_BOOKED_ONLINE.value)
        == []
    )


# ---------------------------------------------------------------------------
# B) Reserva lejana con sena obligatoria: solo Mercado Pago
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_lejano_con_mp_es_422_antes_de_escribir(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    llamadas = _mp_prohibido(monkeypatch)
    t = _lejos(await _tienda(client, "b-whatsapp-lejano", mercadopago=True))
    eventos_antes = await _cuantos(test_session, OutboxMessage)

    res = await _reservar(client, t, metodo="manual")

    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "FAR_BOOKING_REQUIRES_MERCADOPAGO"
    await _nada_escrito(test_session, eventos_antes)
    assert llamadas == []


@pytest.mark.asyncio
@pytest.mark.parametrize("metodo", ["manual", "auto", "mercadopago"])
async def test_tienda_sin_mp_no_toma_la_reserva_lejana_con_sena(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    metodo: str,
) -> None:
    llamadas = _mp_prohibido(monkeypatch)
    t = _lejos(await _tienda(client, f"b-sin-mp-{metodo}"))
    eventos_antes = await _cuantos(test_session, OutboxMessage)

    res = await _reservar(client, t, metodo=metodo)

    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "FAR_BOOKING_UNAVAILABLE"
    assert "Mercado Pago" not in res.json()["message"]
    await _nada_escrito(test_session, eventos_antes)
    assert llamadas == []


@pytest.mark.asyncio
async def test_tienda_sin_mp_reserva_cerca_por_whatsapp_como_siempre(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "b-sin-mp-cerca")

    res = await _reservar(client, t, metodo="manual")

    assert res.status_code == 201, res.text
    assert res.json()["deposit_channel"] == "whatsapp"


@pytest.mark.asyncio
@pytest.mark.parametrize("metodo", ["auto", "mercadopago"])
async def test_mp_lejano_se_reserva_por_mp(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    metodo: str,
) -> None:
    _stub_preference(monkeypatch)
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = _lejos(await _tienda(client, f"b-mp-lejano-{metodo}", mercadopago=True))

    res = await _reservar(client, t, metodo=metodo)

    assert res.status_code == 201, res.text
    cuerpo = res.json()
    assert cuerpo["status"] == AppointmentStatus.PENDING_PAYMENT.value
    assert cuerpo["deposit_channel"] == "mercadopago"
    assert cuerpo["payment_link"]
    cobro = await _cobro(test_session, cuerpo["public_id"])
    assert cobro is not None and cobro.provider == "mercadopago"


@pytest.mark.asyncio
async def test_servicio_sin_sena_lejano_no_cambia(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    usar_cola_de_reservas(monkeypatch, test_session)
    t = _lejos(await _tienda_sin_sena(client, "b-sin-sena-lejano"))

    res = await _reservar(client, t, metodo="manual")

    assert res.status_code == 201, res.text
    assert res.json()["status"] == AppointmentStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_el_cliente_no_muda_la_sena_por_whatsapp_a_una_fecha_lejana(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "b-reprograma-lejos", mercadopago=True)
    reserva = await _reservar(client, t, metodo="manual")
    assert reserva.status_code == 201, reserva.text
    turno = str(reserva.json()["public_id"])
    await _verificar_cliente(client, monkeypatch, t)
    test_session.expire_all()
    eventos_antes = await _cuantos(test_session, OutboxMessage)
    lejos = _lejos(t).dia.replace(hour=11, minute=0, second=0, microsecond=0)

    res = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": lejos.isoformat(),
            "idempotency_key": "b-reprograma-lejos-0001",
        },
    )

    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "FAR_BOOKING_REQUIRES_MERCADOPAGO"
    # Nada se movio: el original sigue esperando su sena, sin turno nuevo.
    original = await _turno(test_session, turno)
    assert original.status == AppointmentStatus.PENDING_PAYMENT.value
    cobro = await _cobro(test_session, turno)
    assert cobro is not None and (cobro.provider, cobro.status) == ("manual", "pending")
    assert await _cuantos(test_session, Appointment) == 1
    assert await _cuantos(test_session, OutboxMessage) == eventos_antes

    # Cerca sigue valiendo (decision del 2026-10-03).
    cerca = t.dia.replace(hour=15, minute=0, second=0, microsecond=0)
    movido = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": cerca.isoformat(),
            "idempotency_key": "b-reprograma-lejos-0002",
        },
    )
    assert movido.status_code == 200, movido.text
    assert movido.json()["deposit_channel"] == "whatsapp"


@pytest.mark.asyncio
async def test_el_cliente_mueve_lejos_un_turno_sin_sena(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    usar_cola_de_reservas(monkeypatch, test_session)
    t = await _tienda_sin_sena(client, "b-sin-sena-mueve")
    reserva = await _reservar(client, t, metodo="manual")
    assert reserva.status_code == 201, reserva.text
    await _verificar_cliente(client, monkeypatch, t)
    lejos = _lejos(t).dia.replace(hour=11, minute=0, second=0, microsecond=0)

    res = await client.patch(
        f"/public/client/appointments/{reserva.json()['public_id']}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": lejos.isoformat(),
            "idempotency_key": "b-sin-sena-mueve-0001",
        },
    )

    assert res.status_code == 200, res.text
    assert res.json()["status"] == AppointmentStatus.CONFIRMED.value


# ---------------------------------------------------------------------------
# B) El cliente ve la regla antes de reservar
# ---------------------------------------------------------------------------


async def _preview(client: AsyncClient, t: _Tienda) -> dict[str, Any]:
    res = await client.get(
        "/public/deposit/preview",
        params={
            "store_public_id": t.store,
            "service_id": t.servicio,
            "starts_at": t.dia.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
        },
    )
    assert res.status_code == 200, res.text
    return dict(res.json())


@pytest.mark.asyncio
async def test_preview_de_la_sena_avisa_la_regla_lejana(
    client: AsyncClient,
) -> None:
    con_mp = await _tienda(client, "b-preview-mp", mercadopago=True)
    sin_mp = await _tienda(client, "b-preview-sin-mp")

    cerca_mp = await _preview(client, con_mp)
    assert (cerca_mp["far_booking"], cerca_mp["online_payment_mandatory"]) == (
        False,
        False,
    )
    assert cerca_mp["booking_blocked_code"] is None

    lejos_mp = await _preview(client, _lejos(con_mp))
    assert (lejos_mp["far_booking"], lejos_mp["online_payment_mandatory"]) == (
        True,
        True,
    )
    assert lejos_mp["booking_blocked_code"] is None

    lejos_sin_mp = await _preview(client, _lejos(sin_mp))
    assert lejos_sin_mp["far_booking"] is True
    assert lejos_sin_mp["booking_blocked_code"] == "FAR_BOOKING_UNAVAILABLE"
    assert (await _preview(client, sin_mp))["booking_blocked_code"] is None


async def _grilla(client: AsyncClient, t: _Tienda) -> list[Any]:
    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": t.store,
            "service_id": t.servicio,
            "date": t.dia.astimezone(timezone.utc).date().isoformat(),
        },
    )
    assert res.status_code == 200, res.text
    return list(res.json())


@pytest.mark.asyncio
async def test_la_grilla_no_ofrece_el_dia_lejano_que_el_alta_rechazaria(
    client: AsyncClient,
) -> None:
    sin_mp = await _tienda(client, "b-grilla-sin-mp")
    con_mp = await _tienda(client, "b-grilla-mp", mercadopago=True)
    sin_sena = await _tienda_sin_sena(client, "b-grilla-sin-sena")

    # Cerca, todos ofrecen horarios.
    assert await _grilla(client, sin_mp)
    # Lejos: la tienda sin MP no ofrece el servicio con sena obligatoria...
    assert await _grilla(client, _lejos(sin_mp)) == []
    # ... la que tiene MP y el servicio sin sena, si.
    assert await _grilla(client, _lejos(con_mp))
    assert await _grilla(client, _lejos(sin_sena))


@pytest.mark.asyncio
async def test_sin_cuenta_de_mp_el_flag_de_cobros_no_alcanza(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Cobros prendidos sin cuenta conectada: no hay "MP usable"
    # (``gateway_has_usable_token``).
    t = await _tienda(client, "b-flag-sin-cuenta")
    await _enable_payments(client, t.token)
    lejos = _lejos(t)
    eventos_antes = await _cuantos(test_session, OutboxMessage)

    res = await _reservar(client, lejos, metodo="auto")

    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "FAR_BOOKING_UNAVAILABLE"
    await _nada_escrito(test_session, eventos_antes)
    # Con la cuenta conectada, la misma reserva entra por MP.
    _stub_preference(monkeypatch)
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    await _configure_gateway(client, t.token)
    # Otra hora: otra clave de idempotencia.
    ok = await _reservar(client, lejos, hora=12, metodo="auto")
    assert ok.status_code == 201, ok.text
    assert ok.json()["deposit_channel"] == "mercadopago"


# ---------------------------------------------------------------------------
# Revision de la PR #236
# ---------------------------------------------------------------------------


def _ventana(dia: datetime, *, horas: int = 4) -> tuple[str, str]:
    inicio = dia.replace(hour=9, minute=0, second=0, microsecond=0)
    return inicio.isoformat(), (inicio + timedelta(hours=horas)).isoformat()


async def _anotarse(
    client: AsyncClient, t: _Tienda, ventana: tuple[str, str], telefono: str
) -> Any:
    return await client.post(
        "/public/waitlist",
        json={
            "store_public_id": t.store,
            "service_id": t.servicio,
            "window_starts_at": ventana[0],
            "window_ends_at": ventana[1],
            "client_name": "Cliente Espera",
            "client_phone": telefono,
            "client_email": f"c{telefono.lstrip('+')}@example.com",
        },
    )


@pytest.mark.asyncio
async def test_la_lista_de_espera_no_toma_una_ventana_lejana_sin_mp(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import modules.waitlist.service as waitlist_service
    from modules.waitlist.model import WaitlistEntry

    rastros: list[tuple[str, str]] = []
    monkeypatch.setattr(
        waitlist_service,
        "report_far_booking_unavailable",
        lambda *, store_id, service_id: rastros.append((store_id, service_id)),
    )
    t = await _tienda(client, "w-lejos-sin-mp")

    lejos = await _anotarse(client, t, _ventana(_lejos(t).dia), "+5491155544401")
    # Empieza cerca y termina lejos: tambien, la lista ofreceria cupos lejanos.
    cruza = await _anotarse(
        client,
        t,
        (_ventana(t.dia)[0], _ventana(_lejos(t).dia)[1]),
        "+5491155544402",
    )

    for res in (lejos, cruza):
        assert res.status_code == 422, res.text
        assert res.json()["error_code"] == "FAR_BOOKING_UNAVAILABLE"
        assert "Mercado Pago" not in res.json()["message"]
    assert await _cuantos(test_session, WaitlistEntry) == 0
    assert await _cuantos(test_session, User, User.role == UserRole.CLIENT) == 0
    assert len(rastros) == 2
    # Cerca sigue como siempre.
    cerca = await _anotarse(client, t, _ventana(t.dia), "+5491155544403")
    assert cerca.status_code == 201, cerca.text


@pytest.mark.asyncio
async def test_la_lista_de_espera_lejana_si_con_mp_o_sin_sena(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    con_mp = await _tienda(client, "w-lejos-mp", mercadopago=True)
    sin_sena = await _tienda_sin_sena(client, "w-lejos-sin-sena")

    for i, t in enumerate((con_mp, sin_sena)):
        res = await _anotarse(client, t, _ventana(_lejos(t).dia), f"+549115554441{i}")
        assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_el_rechazo_lejano_del_alta_deja_rastro(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import modules.public_api.service as public_service

    rastros: list[tuple[str, str]] = []
    monkeypatch.setattr(
        public_service,
        "report_far_booking_unavailable",
        lambda *, store_id, service_id: rastros.append((store_id, service_id)),
    )
    t = _lejos(await _tienda(client, "b-rastro"))

    res = await _reservar(client, t, metodo="auto")

    assert res.status_code == 422, res.text
    assert len(rastros) == 1


def test_el_rastro_lejano_sale_una_vez_por_tienda_y_hora(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.payments.deposit_channels as canales
    from core.observability import OncePer

    eventos: list[dict[str, Any]] = []
    monkeypatch.setattr(canales, "_alertas_lejanas", OncePer(3600.0))
    monkeypatch.setattr(
        canales, "report_exception", lambda exc, **ctx: eventos.append(ctx)
    )

    for reloj in (0.0, 10.0, 3599.0):
        canales.report_far_booking_unavailable(
            store_id="tienda-a", service_id="s1", clock=reloj
        )
    canales.report_far_booking_unavailable(
        store_id="tienda-b", service_id="s1", clock=20.0
    )
    canales.report_far_booking_unavailable(
        store_id="tienda-a", service_id="s2", clock=3601.0
    )

    assert [e["store_id"] for e in eventos] == ["tienda-a", "tienda-b", "tienda-a"]


@pytest.mark.asyncio
async def test_la_vitrina_dice_hasta_cuando_se_reserva_con_sena(
    client: AsyncClient,
) -> None:
    await _tienda(client, "v-limite-sin-mp")
    await _tienda(client, "v-limite-mp", mercadopago=True)
    flag_sin_cuenta = await _tienda(client, "v-limite-flag")
    await _enable_payments(client, flag_sin_cuenta.token)

    async def limite(slug: str) -> Any:
        res = await client.get(f"/public/stores/{slug}")
        assert res.status_code == 200, res.text
        return res.json()["deposit_far_limit_days"]

    assert await limite("v-limite-sin-mp") == FAR_BOOKING_DAYS
    assert await limite("v-limite-flag") == FAR_BOOKING_DAYS
    assert await limite("v-limite-mp") is None


@pytest.mark.asyncio
async def test_varios_servicios_lejos_con_la_sena_en_un_extra(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from tests.integration import test_reserva_varios_servicios as varios

    monkeypatch.setattr(tasks, "_send_email", Buzon())
    # Barba (principal) no pide sena; Corte (extra) la pide obligatoria. La
    # tienda solo tiene WhatsApp.
    t = await varios._tienda(client, "b-varios-lejos")
    lejos = replace(t, dia=t.dia + SEMANAS_LEJOS)
    eventos_antes = await _cuantos(test_session, OutboxMessage)

    res = await varios._reservar(client, lejos, [t.corte], principal=t.barba)

    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "FAR_BOOKING_UNAVAILABLE"
    await _nada_escrito(test_session, eventos_antes)
    dia_lejano = varios._slot(lejos, 13).date().isoformat()
    grilla = await client.get(
        "/public/availability",
        params={
            "store_public_id": t.store,
            "service_id": t.barba,
            "extra_service_id": t.corte,
            "date": dia_lejano,
        },
    )
    assert grilla.status_code == 200, grilla.text
    assert grilla.json() == []
    # Barba sola, sin sena, se ofrece lejos.
    sola = await client.get(
        "/public/availability",
        params={"store_public_id": t.store, "service_id": t.barba, "date": dia_lejano},
    )
    assert sola.status_code == 200 and sola.json(), sola.text
    # Cerca, la misma seleccion se cobra por WhatsApp como siempre.
    cerca = await varios._reservar(client, t, [t.corte], principal=t.barba)
    assert cerca.status_code == 201, cerca.text
    assert cerca.json()["deposit_channel"] == "whatsapp"


@pytest.mark.asyncio
async def test_una_promo_que_deja_la_sena_en_cero_lejos_nace_confirmada(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    usar_cola_de_reservas(monkeypatch, test_session)
    t = _lejos(await _tienda(client, "b-promo-cero"))
    promo = await client.post(
        "/promotions/",
        headers={"Authorization": f"Bearer {t.token}"},
        json={
            "code": "GRATIS100",
            "title": "Gratis",
            "promotion_type": "fixed",
            "value": "10000.00",
            "is_active": True,
        },
    )
    assert promo.status_code == 201, promo.text

    res = await client.post(
        "/public/appointments",
        json={
            "store_public_id": t.store,
            "service_id": t.servicio,
            "staff_id": t.staff,
            "starts_at": t.dia.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Promo",
            "client_phone": "+5491155544499",
            "client_email": "cliente-promo@example.com",
            "payment_method": "manual",
            "promotion_code": "GRATIS100",
            "accepts_terms": True,
            "idempotency_key": "b-promo-cero-0001",
        },
    )

    # Sena obligatoria de importe cero: no hay cobro, la regla lejana no
    # alcanza y nace confirmada (decision A).
    assert res.status_code == 201, res.text
    assert res.json()["status"] == AppointmentStatus.CONFIRMED.value
    assert res.json()["payment_required"] is False
    assert await _cobro(test_session, res.json()["public_id"]) is None


@pytest.mark.asyncio
async def test_mis_turnos_muestra_la_reserva_sin_cobro_confirmada_y_autogestionable(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    usar_cola_de_reservas(monkeypatch, test_session)
    t = await _tienda_sin_sena(client, "a-mis-turnos")
    reserva = await _reservar(client, t, metodo="manual")
    assert reserva.status_code == 201, reserva.text
    await _verificar_cliente(client, monkeypatch, t)

    res = await client.get(f"/public/client/{t.store}/{TELEFONO}/appointments")

    assert res.status_code == 200, res.text
    turno = reserva.json()["public_id"]
    [item] = [i for i in res.json()["appointments"] if i["public_id"] == turno]
    assert item["status"] == AppointmentStatus.CONFIRMED.value
    assert (item["can_cancel"], item["can_reschedule"]) == (True, True)
