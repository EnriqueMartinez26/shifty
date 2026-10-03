"""Regla 3 con una sena por WhatsApp (``Payment.provider = "manual"``).

Revision 4R de la PR #108 (R3 CRITICO): la regla 3 ("un turno con cobro vivo
no se suelta sin vencer el cobro") no tenia pruebas con el cobro manual. Lo
que fija este archivo:

- el CLIENTE puede cancelar y reprogramar desde "Mis turnos" un turno con la
  sena por WhatsApp pendiente (propuesta del coordinador aceptada por Mateo,
  2026-10-03): la carrera con MP que justifica la regla no existe porque no
  pasa plata por la plataforma. Cancelar vence el cobro por el grafo, sin
  ``payment.preference.expire`` ni llamadas a MP; reprogramar muda la sena al
  turno nuevo con el plazo recalculado. La de MP sigue frenada;
- el PANEL cancela venciendo el cobro igual, sin MP; reprogramar sigue
  frenado (409 ``DEPOSIT_PENDING_RESCHEDULE_DENIED``, eleccion tecnica del
  coordinador: primero se registra el pago); "Confirmar" tampoco deja un
  turno confirmado con el cobro vivo (409 ``DEPOSIT_PENDING_CONFIRM_DENIED``);
- ``manual-confirm`` avisa "turno confirmado" solo cuando confirma un turno
  futuro (R3 W5);
- el reembolso de un cobro manual no pide el flag ``payments`` (R1 W2, R3 W6);
- un pago de MP que entra sobre una sena ya registrada a mano avisa al dueno
  una vez (R1 W1).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.config import settings
from core.utils import ensure_utc_aware
from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import Notification, NotificationType
from modules.notifications.tasks import EVENT_APPOINTMENT_CONFIRMED
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import OutboxMessage, Payment, PaymentStatus
from modules.payments.service import EVENT_PREFERENCE_EXPIRE
from modules.services.model import Service
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    webhook_signature_headers,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import _stub_preference
from tests.integration.test_sena_por_mp_o_whatsapp import (
    SENA,
    _cobro,
    _eventos,
    _mp_prohibido,
    _reservar,
    _Tienda,
    _tienda,
    _turno,
)

TELEFONO = "+5491155544433"  # el de ``_reservar``


async def _verificar_cliente(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, t: _Tienda
) -> None:
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    pedido = await client.post(
        "/public/otp/request",
        json={"store_public_id": t.store, "phone": TELEFONO, "channel": "whatsapp"},
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": t.store,
            "phone": TELEFONO,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text


async def _sena_por_whatsapp(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, slug: str
) -> tuple[_Tienda, str]:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, slug)
    reserva = await _reservar(client, t)
    assert reserva.status_code == 201, reserva.text
    assert reserva.json()["deposit_channel"] == "whatsapp"
    return t, str(reserva.json()["public_id"])


async def _vencimientos(session: AsyncSession) -> list[OutboxMessage]:
    return await _eventos(session, EVENT_PREFERENCE_EXPIRE)


# ---------------------------------------------------------------------------
# Cliente: cancelar y reprogramar desde "Mis turnos"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_cliente_cancela_su_sena_por_whatsapp_y_el_cobro_vence_sin_mp(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _sena_por_whatsapp(client, monkeypatch, "r3-cliente-cancela")
    await _verificar_cliente(client, monkeypatch, t)
    llamadas = _mp_prohibido(monkeypatch)

    res = await client.patch(
        f"/public/client/appointments/{turno}/cancel",
        json={"phone": TELEFONO, "reason": "No llego"},
    )

    assert res.status_code == 200, res.text
    assert (await _turno(test_session, turno)).status == "cancelled"
    cobro = await _cobro(test_session, turno)
    assert cobro is not None and cobro.status == PaymentStatus.EXPIRED.value
    assert await _vencimientos(test_session) == []
    assert llamadas == []
    avisos = await _eventos(
        test_session, NotificationType.APPOINTMENT_CANCELLED_BY_CLIENT.value
    )
    assert [a.payload["appointment_id"] for a in avisos] == [turno]


@pytest.mark.asyncio
async def test_el_cliente_reprograma_y_la_sena_se_muda_con_el_plazo_nuevo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _sena_por_whatsapp(client, monkeypatch, "r3-cliente-reprograma")
    await _verificar_cliente(client, monkeypatch, t)
    original = await _cobro(test_session, turno)
    assert original is not None
    monto, regla = original.amount, original.deposit_rule
    llamadas = _mp_prohibido(monkeypatch)
    nuevo_inicio = t.dia.replace(hour=15, minute=0, second=0, microsecond=0)

    res = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": nuevo_inicio.isoformat(),
            "idempotency_key": "r3-cliente-reprograma-0001",
        },
    )

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    nuevo = cuerpo["public_id"]
    assert cuerpo["status"] == AppointmentStatus.PENDING_PAYMENT.value
    assert cuerpo["deposit_channel"] == "whatsapp"
    plazo = nuevo_inicio - timedelta(hours=2)
    assert datetime.fromisoformat(cuerpo["deposit_deadline"]) == plazo
    # El original se solto y su cobro vencio por el grafo, sin MP.
    assert (await _turno(test_session, turno)).status == "cancelled"
    viejo = await _cobro(test_session, turno)
    assert viejo is not None and viejo.status == PaymentStatus.EXPIRED.value
    # El nuevo espera la MISMA sena, con el plazo contra el horario nuevo.
    turno_nuevo = await _turno(test_session, nuevo)
    assert turno_nuevo.status == AppointmentStatus.PENDING_PAYMENT.value
    assert turno_nuevo.expires_at is not None
    assert ensure_utc_aware(turno_nuevo.expires_at) == plazo
    cobro_nuevo = await _cobro(test_session, nuevo)
    assert cobro_nuevo is not None
    assert (cobro_nuevo.provider, cobro_nuevo.status) == ("manual", "pending")
    assert cobro_nuevo.amount == SENA == monto
    assert cobro_nuevo.deposit_rule == regla
    # El dueno recibe el plazo nuevo (el aviso anterior ya no vale).
    avisos = await _eventos(
        test_session, NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value
    )
    del_nuevo = [a for a in avisos if a.payload["appointment_id"] == nuevo]
    assert len(del_nuevo) == 1
    assert del_nuevo[0].payload["channel"] == "whatsapp"
    assert datetime.fromisoformat(str(del_nuevo[0].payload["expires_at"])) == plazo
    assert await _vencimientos(test_session) == []
    assert llamadas == []


@pytest.mark.asyncio
async def test_el_historial_ofrece_cancelar_la_sena_por_whatsapp_y_no_la_de_mp(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_preference(monkeypatch)
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "r3-historial", mercadopago=True)
    por_whatsapp = await _reservar(client, t, hora=10, metodo="manual")
    por_mp = await _reservar(client, t, hora=12, metodo="mercadopago")
    assert por_whatsapp.status_code == por_mp.status_code == 201
    await _verificar_cliente(client, monkeypatch, t)

    res = await client.get(f"/public/client/{t.store}/{TELEFONO}/appointments")

    assert res.status_code == 200, res.text
    flags = {
        item["public_id"]: (item["can_cancel"], item["can_reschedule"])
        for item in res.json()["appointments"]
    }
    assert flags[por_whatsapp.json()["public_id"]] == (True, True)
    assert flags[por_mp.json()["public_id"]] == (False, False)
    # Y la accion coincide con el flag: la de MP sigue frenada (regla 3).
    rebote = await client.patch(
        f"/public/client/appointments/{por_mp.json()['public_id']}/cancel",
        json={"phone": TELEFONO},
    )
    assert rebote.status_code == 409, rebote.text
    assert rebote.json()["error_code"] == "PAYMENT_APPOINTMENT_REQUIRES_RELEASE"


# ---------------------------------------------------------------------------
# Panel: cancelar, reprogramar y confirmar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_panel_cancela_la_sena_por_whatsapp_sin_publicar_ni_llamar_a_mp(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _sena_por_whatsapp(client, monkeypatch, "r3-panel-cancela")
    llamadas = _mp_prohibido(monkeypatch)

    res = await client.patch(
        f"/appointments/{turno}/cancel", headers=auth_headers(t.token)
    )

    assert res.status_code == 200, res.text
    assert (await _turno(test_session, turno)).status == "cancelled"
    cobro = await _cobro(test_session, turno)
    assert cobro is not None and cobro.status == PaymentStatus.EXPIRED.value
    assert await _vencimientos(test_session) == []
    assert llamadas == []


@pytest.mark.asyncio
async def test_el_panel_no_reprograma_una_sena_por_whatsapp_pendiente(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eleccion tecnica del coordinador: la regla del panel sigue siendo una
    sola (opcion A). El personal registra el pago y despues lo mueve; sin
    pagar lo mueve el cliente, con el plazo recalculado."""
    t, turno = await _sena_por_whatsapp(client, monkeypatch, "r3-panel-reprograma")

    res = await client.patch(
        f"/appointments/{turno}/reschedule",
        headers=auth_headers(t.token),
        json={
            "new_starts_at": t.dia.replace(
                hour=15, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": f"r3-panel-reprograma-{turno}",
        },
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "DEPOSIT_PENDING_RESCHEDULE_DENIED"
    assert (await _turno(test_session, turno)).status == "pending_payment"
    cobro = await _cobro(test_session, turno)
    assert cobro is not None and cobro.status == PaymentStatus.PENDING.value


@pytest.mark.asyncio
@pytest.mark.parametrize("metodo", ["manual", "mercadopago"])
async def test_confirmar_no_deja_un_turno_confirmado_con_la_sena_viva(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    metodo: str,
) -> None:
    _stub_preference(monkeypatch)
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, f"r3-confirmar-{metodo}", mercadopago=True)
    reserva = await _reservar(client, t, metodo=metodo)
    turno = reserva.json()["public_id"]

    res = await client.patch(
        f"/appointments/{turno}/confirm", headers=auth_headers(t.token)
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "DEPOSIT_PENDING_CONFIRM_DENIED"
    assert "Cobros" in res.json()["message"]
    assert (await _turno(test_session, turno)).status == "pending_payment"
    assert await _eventos(test_session, EVENT_APPOINTMENT_CONFIRMED) == []


# ---------------------------------------------------------------------------
# manual-confirm: el mail de "turno confirmado" (R3 W5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cobrar_en_efectivo_una_sena_de_mp_confirma_y_avisa_una_vez(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_preference(monkeypatch)
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "r3-efectivo-mp", mercadopago=True)
    reserva = await _reservar(client, t, metodo="mercadopago")
    turno = reserva.json()["public_id"]

    res = await client.post(
        f"/payments/{turno}/manual-confirm",
        headers=auth_headers(t.token),
        json={"notes": "pago en el local"},
    )

    assert res.status_code == 200, res.text
    assert (await _turno(test_session, turno)).status == "confirmed"
    confirmados = await _eventos(test_session, EVENT_APPOINTMENT_CONFIRMED)
    assert [e.payload["appointment_id"] for e in confirmados] == [turno]
    # El checkout de MP que quedo vivo se manda a vencer (ya se cobro).
    assert len(await _vencimientos(test_session)) == 1


@pytest.mark.asyncio
async def test_registrar_el_pago_de_un_turno_pasado_no_le_escribe_al_cliente(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un turno pasado lo registra la tienda (D-20260925-01): no hay "turno
    confirmado" para alguien que ya estuvo."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, "r3-pasado")
    await test_session.execute(
        update(Service)
        .where(Service.public_id == t.servicio)
        .values(deposit_mode="none", deposit_type="full", deposit_amount=None)
    )
    await test_session.commit()
    reserva = await _reservar(client, t)
    turno = reserva.json()["public_id"]
    assert reserva.json()["status"] == "pending"
    inicio = datetime.now(timezone.utc) - timedelta(hours=3)
    await test_session.execute(
        update(Appointment)
        .where(Appointment.id == turno)
        .values(starts_at=inicio, ends_at=inicio + timedelta(minutes=30))
    )
    await test_session.commit()

    res = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(t.token), json={}
    )

    assert res.status_code == 200, res.text
    assert (await _turno(test_session, turno)).status == "confirmed"
    assert await _eventos(test_session, EVENT_APPOINTMENT_CONFIRMED) == []


# ---------------------------------------------------------------------------
# Reembolso sin el flag de cobros (R1 W2, R3 W6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_reembolso_de_una_sena_por_whatsapp_no_pide_el_flag(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _sena_por_whatsapp(client, monkeypatch, "r3-reembolso")
    flags = await client.get("/stores/me/feature-flags", headers=auth_headers(t.token))
    assert flags.json()["flags"]["payments"] is False
    confirmado = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(t.token), json={}
    )
    assert confirmado.status_code == 200, confirmado.text
    cobro = await _cobro(test_session, turno)
    assert cobro is not None

    res = await client.post(
        f"/payments/{cobro.id}/refund",
        headers=auth_headers(t.token),
        json={"manual": True, "reason": "el cliente no pudo venir"},
    )

    assert res.status_code == 200, res.text
    assert res.json()["status"] == PaymentStatus.REFUNDED.value


@pytest.mark.asyncio
async def test_el_reembolso_de_un_cobro_de_mp_sigue_pidiendo_el_flag(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    t = await _tienda(client, "r3-reembolso-mp")
    reserva = await _reservar(client, t)
    cobro = await _cobro(test_session, reserva.json()["public_id"])
    assert cobro is not None
    # Un cobro de MP acreditado por el webhook (sin flag ya no deberia haber).
    cobro.provider = "mercadopago"
    cobro.apply_status(PaymentStatus.APPROVED.value)
    await test_session.commit()

    res = await client.post(
        f"/payments/{cobro.id}/refund",
        headers=auth_headers(t.token),
        json={"manual": True},
    )

    assert res.status_code == 403, res.text
    assert res.json()["error_code"] == "FEATURE_DISABLED"


# ---------------------------------------------------------------------------
# Pago doble: MP aprueba una sena ya registrada a mano (R1 W1)
# ---------------------------------------------------------------------------


def _mp_con_pago(monkeypatch: pytest.MonkeyPatch, remoto: dict[str, Any]) -> None:
    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return {
                "id": "pref-doble",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=d",
            }
        return remoto

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


async def _webhook(client: AsyncClient, store: str, evento: str, pago: str) -> None:
    res = await client.post(
        f"/payments/webhooks/mercadopago?store_id={store}",
        json={"id": evento, "type": "payment", "data": {"id": pago}},
        headers=webhook_signature_headers(
            secret="secret-demo",
            data_id=pago,
            request_id=f"req-{evento}",
            ts="1710000000",
        ),
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_un_pago_de_mp_sobre_una_sena_registrada_a_mano_avisa_una_vez(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mp_con_pago(monkeypatch, {})
    t = await _tienda(client, "r3-pago-doble", mercadopago=True)
    reserva = await _reservar(client, t, metodo="manual")
    turno = reserva.json()["public_id"]
    # La tienda le manda el link de MP y despues el cliente paga por fuera.
    link = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(t.token)
    )
    assert link.status_code == 200, link.text
    confirmado = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(t.token), json={}
    )
    assert confirmado.status_code == 200, confirmado.text
    cobro = await _cobro(test_session, turno)
    assert cobro is not None and cobro.status == PaymentStatus.MANUAL_CONFIRMED.value
    _mp_con_pago(
        monkeypatch,
        {
            "id": "mp-pago-doble",
            "status": "approved",
            "external_reference": cobro.current_external_reference,
            "preference_id": cobro.preference_id,
            "transaction_amount": float(cobro.amount),
            "currency_id": cobro.currency,
            "metadata": {"appointment_id": turno},
        },
    )

    # MP reentrega el mismo pago con otro id de notificacion.
    await _webhook(client, t.store, "evt-doble-1", "mp-pago-doble")
    await _webhook(client, t.store, "evt-doble-2", "mp-pago-doble")

    cobro = await _cobro(test_session, turno)
    assert cobro is not None and cobro.status == PaymentStatus.MANUAL_CONFIRMED.value
    assert Decimal(str(cobro.amount)) == SENA
    avisos = await _eventos(
        test_session, NotificationType.PAYMENT_ON_REPLACED_LINK.value
    )
    assert len(avisos) == 1, [a.payload for a in avisos]
    assert avisos[0].payload["duplicado"] is True
    assert avisos[0].payload["link_vigente"] is True
    assert avisos[0].payload["aviso"] == "pago:mp-pago-doble"

    await process_outbox_batch(test_session)
    aviso = (
        await test_session.execute(
            select(Notification).where(
                Notification.type == NotificationType.PAYMENT_ON_REPLACED_LINK.value
            )
        )
    ).scalar_one()
    assert aviso.title == "Pago duplicado"
    assert "ya habías registrado a mano" in (aviso.body or "")
    assert "$ 3.000" in (aviso.body or "")


@pytest.mark.asyncio
async def test_la_reentrega_de_un_pago_ya_acreditado_por_mp_no_avisa_doble(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El aviso es para la sena registrada a mano: el ``approved`` reentregado
    de un cobro que acredito MP es el camino normal y no alerta."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mp_con_pago(monkeypatch, {})
    t = await _tienda(client, "r3-reentrega", mercadopago=True)
    reserva = await _reservar(client, t, metodo="mercadopago")
    turno = reserva.json()["public_id"]
    cobro = await _cobro(test_session, turno)
    assert cobro is not None
    _mp_con_pago(
        monkeypatch,
        {
            "id": "mp-pago-ok",
            "status": "approved",
            "external_reference": cobro.current_external_reference,
            "preference_id": cobro.preference_id,
            "transaction_amount": float(cobro.amount),
            "currency_id": cobro.currency,
            "metadata": {"appointment_id": turno},
        },
    )

    await _webhook(client, t.store, "evt-ok-1", "mp-pago-ok")
    await _webhook(client, t.store, "evt-ok-2", "mp-pago-ok")

    cobro = await _cobro(test_session, turno)
    assert cobro is not None and cobro.status == PaymentStatus.APPROVED.value
    assert (
        await _eventos(test_session, NotificationType.PAYMENT_ON_REPLACED_LINK.value)
        == []
    )
    pagos = (await test_session.execute(select(Payment))).scalars().all()
    assert len(list(pagos)) == 1
