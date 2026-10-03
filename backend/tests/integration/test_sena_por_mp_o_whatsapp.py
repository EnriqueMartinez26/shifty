"""Una sena obligatoria se paga por Mercado Pago o por WhatsApp.

Decision de Mateo (2026-10-03): la sena obligatoria se cobra por Mercado Pago
o por WhatsApp (transferencia o efectivo coordinados en el chat). Cuando el
cliente paga por WhatsApp, el personal de la tienda confirma el pago a mano
desde el panel.

Bug de QA en navegador (2026-10-02, tienda ``barberia-sentinel``, stack
local): el servicio "Servicio VIP Completo" pide 30% de sena; la tienda tiene
MP sin conectar y el flag ``payments`` apagado. La reserva publica devolvia
``payment_required: false`` sin link, la pantalla de exito no mencionaba la
sena, el aviso al dueno decia "Confirmalo cuando recibas la transferencia" y
"Confirmar manual" en Cobros respondia 403 ``FEATURE_DISABLED``: nadie podia
completar el pago.

Ahora:

- una sena obligatoria sin ningun canal (MP conectado con los cobros
  prendidos, o un WhatsApp valido de la tienda) no se reserva: 409
  ``DEPOSIT_CHANNEL_UNAVAILABLE`` antes de escribir nada;
- por WhatsApp el turno nace ``pending_payment`` con la misma retencion que
  MP y un cobro ``pending`` de proveedor ``manual`` (sin link): el panel lo
  confirma a mano sin MP ni flag, y si nadie lo confirma, el job de
  retenciones lo vence por el grafo sin preguntarle nada a MP;
- el camino de MP no cambia.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.config import settings
from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import Notification, NotificationType
from modules.notifications.tasks import EVENT_APPOINTMENT_CONFIRMED
from modules.payments.jobs import expire_unpaid_appointments, process_outbox_batch
from modules.payments.model import OutboxMessage, Payment, PaymentStatus
from modules.payments.service import EVENT_PREFERENCE_EXPIRE
from modules.services.model import Service
from modules.waitlist.events import EVENT_SLOT_RELEASED
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
    _stub_preference,
)

WHATSAPP_DE_LA_TIENDA = "11 5555 0303"
PRECIO = Decimal("10000")
SENA = Decimal("3000.00")  # 30 % de 10000


@dataclass(frozen=True)
class _Tienda:
    store: str
    token: str
    servicio: str
    staff: str
    dia: datetime


async def _whatsapp(client: AsyncClient, token: str, numero: str | None) -> None:
    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"whatsapp_number": numero}
    )
    assert res.status_code == 200, res.text


async def _tienda(
    client: AsyncClient,
    slug: str,
    *,
    mercadopago: bool = False,
) -> _Tienda:
    """Tienda con WhatsApp, un servicio de sena obligatoria del 30 % y su
    profesional; con ``mercadopago``, tambien MP conectado y cobros prendidos."""
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    await _whatsapp(client, token, WHATSAPP_DE_LA_TIENDA)
    if mercadopago:
        await _enable_payments(client, token)
        await _configure_gateway(client, token)
    servicio = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return _Tienda(store, token, servicio, staff, dia)


async def _reservar(
    client: AsyncClient, t: _Tienda, *, hora: int = 11, metodo: str = "manual"
) -> Any:
    return await client.post(
        "/public/appointments",
        json={
            "store_public_id": t.store,
            "service_id": t.servicio,
            "staff_id": t.staff,
            "starts_at": t.dia.replace(
                hour=hora, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Sena",
            "client_phone": "+5491155544433",
            "client_email": "cliente-sena@example.com",
            "payment_method": metodo,
            "accepts_terms": True,
            "idempotency_key": f"sena-{t.store}-{hora}-{metodo}",
        },
    )


async def _cobro(session: AsyncSession, turno: str) -> Payment | None:
    session.expire_all()
    return (
        await session.execute(select(Payment).where(Payment.appointment_id == turno))
    ).scalar_one_or_none()


async def _turno(session: AsyncSession, turno: str) -> Appointment:
    session.expire_all()
    return (
        await session.execute(select(Appointment).where(Appointment.id == turno))
    ).scalar_one()


async def _eventos(session: AsyncSession, tipo: str) -> list[OutboxMessage]:
    session.expire_all()
    return list(
        (
            await session.execute(
                select(OutboxMessage).where(OutboxMessage.event_type == tipo)
            )
        )
        .scalars()
        .all()
    )


def _mp_prohibido(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Cualquier llamada a la API de MP queda anotada (y falla)."""
    llamadas: list[str] = []

    async def prohibido(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        llamadas.append(path)
        raise AssertionError(f"no se le pregunta a MP por una sena manual: {path}")

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", prohibido)
    return llamadas


# ---------------------------------------------------------------------------
# Reproduccion: sena obligatoria sin canal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_una_sena_obligatoria_sin_canal_no_crea_un_turno_impagable(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El caso de ``barberia-sentinel``: sin MP, sin flag y sin WhatsApp."""
    t = await _tienda(client, "sena-sin-canal")
    # La tienda borro su WhatsApp despues de configurar la sena (o la sena es
    # anterior a esta rama): el servicio la pide aunque hoy no haya canal.
    await _whatsapp(client, t.token, None)
    assert (
        await test_session.execute(
            select(Service.deposit_mode).where(Service.public_id == t.servicio)
        )
    ).scalar_one() == "required"

    res = await _reservar(client, t)

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "DEPOSIT_CHANNEL_UNAVAILABLE"
    assert "Mercado Pago" not in res.json()["message"]
    test_session.expire_all()
    turnos = (await test_session.execute(select(Appointment))).scalars().all()
    assert list(turnos) == []


# ---------------------------------------------------------------------------
# Camino de WhatsApp
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_sena_por_whatsapp_retiene_el_turno_como_la_de_mercado_pago(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    llamadas = _mp_prohibido(monkeypatch)
    t = await _tienda(client, "sena-whatsapp-retiene")
    antes = datetime.now(timezone.utc)

    res = await _reservar(client, t)

    assert res.status_code == 201, res.text
    cuerpo = res.json()
    assert cuerpo["status"] == AppointmentStatus.PENDING_PAYMENT.value
    assert cuerpo["payment_required"] is True
    assert cuerpo["payment_link"] is None
    assert cuerpo["payment_status"] == PaymentStatus.PENDING.value
    assert Decimal(str(cuerpo["payment_amount"])) == SENA
    turno = await _turno(test_session, cuerpo["public_id"])
    # La misma retencion corta que MP: el cupo vuelve si nadie confirma.
    vence = turno.expires_at
    assert vence is not None
    if vence.tzinfo is None:
        vence = vence.replace(tzinfo=timezone.utc)
    assert vence <= antes + timedelta(minutes=settings.PAYMENT_HOLD_MINUTES + 1)
    cobro = await _cobro(test_session, turno.id)
    assert cobro is not None
    assert cobro.provider == "manual"
    assert cobro.status == PaymentStatus.PENDING.value
    assert cobro.amount == SENA
    assert cobro.deposit_rule is not None
    assert llamadas == []


@pytest.mark.asyncio
async def test_el_personal_confirma_la_sena_de_whatsapp_sin_mp_ni_flag(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    llamadas = _mp_prohibido(monkeypatch)
    t = await _tienda(client, "sena-whatsapp-confirma")
    reserva = await _reservar(client, t)
    assert reserva.status_code == 201, reserva.text
    turno = reserva.json()["public_id"]

    res = await client.post(
        f"/payments/{turno}/manual-confirm",
        headers=auth_headers(t.token),
        json={"notes": "transferencia por WhatsApp"},
    )

    assert res.status_code == 200, res.text
    assert res.json()["status"] == PaymentStatus.MANUAL_CONFIRMED.value
    # El importe es la sena, no el precio del servicio.
    assert Decimal(str(res.json()["amount"])) == SENA
    assert (await _turno(test_session, turno)).status == "confirmed"
    # "Turno confirmado" al cliente por el outbox, en la misma transaccion.
    confirmados = await _eventos(test_session, EVENT_APPOINTMENT_CONFIRMED)
    assert [e.payload["appointment_id"] for e in confirmados] == [turno]
    # Un placeholder no existe en MP: no hay link que vencer.
    assert await _eventos(test_session, EVENT_PREFERENCE_EXPIRE) == []
    assert llamadas == []


@pytest.mark.asyncio
async def test_confirmar_dos_veces_no_repite_el_mail_de_confirmacion(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    t = await _tienda(client, "sena-whatsapp-doble")
    reserva = await _reservar(client, t)
    turno = reserva.json()["public_id"]

    for _ in range(2):
        res = await client.post(
            f"/payments/{turno}/manual-confirm",
            headers=auth_headers(t.token),
            json={},
        )
        assert res.status_code == 200, res.text

    assert len(await _eventos(test_session, EVENT_APPOINTMENT_CONFIRMED)) == 1


@pytest.mark.asyncio
async def test_el_aviso_al_dueno_le_dice_que_confirme_cuando_le_paguen_por_whatsapp(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "sena-whatsapp-aviso")
    reserva = await _reservar(client, t)
    assert reserva.status_code == 201, reserva.text

    await process_outbox_batch(test_session)

    aviso = (
        await test_session.execute(
            select(Notification).where(
                Notification.type
                == NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value
            )
        )
    ).scalar_one()
    assert aviso.appointment_id == reserva.json()["public_id"]
    cuerpo = aviso.body or ""
    assert "Confirmalo cuando te paguen por WhatsApp" in cuerpo, cuerpo
    assert "3000" in cuerpo, cuerpo
    assert "transferencia" not in cuerpo, cuerpo


@pytest.mark.asyncio
async def test_la_retencion_vencida_de_whatsapp_libera_el_turno_sin_consultar_a_mp(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, "sena-whatsapp-vence")
    reserva = await _reservar(client, t)
    turno = reserva.json()["public_id"]
    await test_session.execute(
        update(Appointment)
        .where(Appointment.id == turno)
        .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    )
    await test_session.commit()
    llamadas = _mp_prohibido(monkeypatch)

    resultado = await expire_unpaid_appointments(test_session)

    assert resultado["expired"] == 1, resultado
    assert resultado["held"] == 0, resultado
    assert llamadas == []
    assert (await _turno(test_session, turno)).status == "expired"
    cobro = await _cobro(test_session, turno)
    assert cobro is not None and cobro.status == PaymentStatus.EXPIRED.value
    liberados = await _eventos(test_session, EVENT_SLOT_RELEASED)
    assert [e.payload["appointment_id"] for e in liberados] == [turno]
    # Y una confirmacion tardia ya no revive el turno (regla 3).
    tarde = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(t.token), json={}
    )
    assert tarde.status_code == 409, tarde.text
    assert tarde.json()["error_code"] == "APPOINTMENT_NOT_PAYABLE"


# ---------------------------------------------------------------------------
# Camino de Mercado Pago: sin cambios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("metodo", ["mercadopago", "auto"])
async def test_con_mp_conectado_la_sena_sigue_por_mercado_pago(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    metodo: str,
) -> None:
    _stub_preference(monkeypatch)
    t = await _tienda(client, f"sena-mp-{metodo}", mercadopago=True)

    res = await _reservar(client, t, metodo=metodo)

    assert res.status_code == 201, res.text
    cuerpo = res.json()
    assert cuerpo["status"] == AppointmentStatus.PENDING_PAYMENT.value
    assert cuerpo["payment_required"] is True
    assert cuerpo["payment_link"] == (
        "https://www.mercadopago.com/checkout/v1/redirect?pref=hardening"
    )
    cobro = await _cobro(test_session, cuerpo["public_id"])
    assert cobro is not None
    assert cobro.provider == "mercadopago"
    assert cobro.preference_id == "pref-hardening"
    # Sin aviso de "confirmalo a mano": a MP lo acredita el webhook.
    assert (
        await _eventos(
            test_session, NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value
        )
        == []
    )


@pytest.mark.asyncio
async def test_con_mp_conectado_el_cliente_puede_elegir_whatsapp(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    llamadas = _mp_prohibido(monkeypatch)
    t = await _tienda(client, "sena-mp-elige-whatsapp", mercadopago=True)

    res = await _reservar(client, t, metodo="manual")

    assert res.status_code == 201, res.text
    assert res.json()["status"] == AppointmentStatus.PENDING_PAYMENT.value
    assert res.json()["payment_link"] is None
    cobro = await _cobro(test_session, res.json()["public_id"])
    assert cobro is not None and cobro.provider == "manual"
    assert llamadas == []


@pytest.mark.asyncio
async def test_el_link_del_panel_sobre_una_sena_de_whatsapp_la_pasa_a_mercado_pago(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si la tienda le manda despues el link de MP, el cobro deja de ser
    manual: el job de retenciones y la conciliacion vuelven a consultarlo."""
    t = await _tienda(client, "sena-whatsapp-a-mp", mercadopago=True)
    reserva = await _reservar(client, t, metodo="manual")
    turno = reserva.json()["public_id"]
    _stub_preference(monkeypatch)

    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.token)
    )

    assert link.status_code == 200, link.text
    cobro = await _cobro(test_session, turno)
    assert cobro is not None
    assert cobro.provider == "mercadopago"
    assert cobro.preference_id == "pref-hardening"


# ---------------------------------------------------------------------------
# Configuracion: sin canal no se guarda una sena obligatoria
# ---------------------------------------------------------------------------


def _servicio(deposit_mode: str) -> dict[str, Any]:
    return {
        "name": "Servicio VIP Completo",
        "duration_minutes": 30,
        "price": float(PRECIO),
        "deposit_mode": deposit_mode,
        "deposit_type": "percent",
        "deposit_amount": 30,
    }


@pytest.mark.asyncio
async def test_no_se_crea_una_sena_obligatoria_sin_canal(client: AsyncClient) -> None:
    _store, token = await register_and_login(
        client, slug="sena-config-alta", email="sena-config-alta@t.com"
    )

    res = await client.post(
        "/services/", headers=auth_headers(token), json=_servicio("required")
    )

    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "DEPOSIT_CHANNEL_REQUIRED"
    assert "WhatsApp" in res.json()["message"]
    assert "Mercado Pago" in res.json()["message"]
    # Una sena opcional o ninguna no necesita canal.
    for modo in ("optional", "none"):
        ok = await client.post(
            "/services/", headers=auth_headers(token), json=_servicio(modo)
        )
        assert ok.status_code == 201, ok.text


@pytest.mark.asyncio
async def test_el_flag_de_cobros_sin_mp_conectado_no_es_un_canal(
    client: AsyncClient,
) -> None:
    _store, token = await register_and_login(
        client, slug="sena-config-flag", email="sena-config-flag@t.com"
    )
    await _enable_payments(client, token)

    sin_conectar = await client.post(
        "/services/", headers=auth_headers(token), json=_servicio("required")
    )
    assert sin_conectar.status_code == 422, sin_conectar.text

    await _configure_gateway(client, token)
    conectado = await client.post(
        "/services/", headers=auth_headers(token), json=_servicio("required")
    )
    assert conectado.status_code == 201, conectado.text


@pytest.mark.asyncio
async def test_un_whatsapp_que_no_se_puede_leer_no_es_un_canal(
    client: AsyncClient,
) -> None:
    _store, token = await register_and_login(
        client, slug="sena-config-wa", email="sena-config-wa@t.com"
    )
    await _whatsapp(client, token, "llamame al local")

    invalido = await client.post(
        "/services/", headers=auth_headers(token), json=_servicio("required")
    )
    assert invalido.status_code == 422, invalido.text

    await _whatsapp(client, token, WHATSAPP_DE_LA_TIENDA)
    valido = await client.post(
        "/services/", headers=auth_headers(token), json=_servicio("required")
    )
    assert valido.status_code == 201, valido.text


@pytest.mark.asyncio
async def test_no_se_edita_un_servicio_a_sena_obligatoria_sin_canal(
    client: AsyncClient,
) -> None:
    _store, token = await register_and_login(
        client, slug="sena-config-edita", email="sena-config-edita@t.com"
    )
    alta = await client.post(
        "/services/", headers=auth_headers(token), json=_servicio("optional")
    )
    assert alta.status_code == 201, alta.text
    servicio = cast(str, alta.json()["public_id"])

    res = await client.patch(
        f"/services/{servicio}",
        headers=auth_headers(token),
        json={"deposit_mode": "required"},
    )

    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "DEPOSIT_CHANNEL_REQUIRED"
    # Un PATCH que no toca la sena sigue pasando.
    nombre = await client.patch(
        f"/services/{servicio}", headers=auth_headers(token), json={"name": "Otro"}
    )
    assert nombre.status_code == 200, nombre.text
