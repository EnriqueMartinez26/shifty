"""Flujos de cobro de punta a punta contra el emulador de Mercado Pago.

El dueno no tiene credenciales de sandbox y hasta aca todo MP estaba
monkeypatcheado en los tests (se reemplazaba ``_mercadopago_api_request``).
Aca no se toca el cliente de MP: el backend arma sus requests, las firma con
el token de la tienda y las manda por HTTP real al emulador
(``tests/e2e/mp_emulator.py``) con su propio ``httpx``, timeouts y circuit
breaker. Los routers, services y jobs son los de verdad.

Cada test mira el estado en la base (el cobro por la entidad ``Payment``, el
turno, el outbox y el inbox), lo que el emulador recibio y que no haya 500.

Lo que esto NO prueba (seccion 4 de CLAUDE.md): corre en SQLite, asi que ni
RLS, ni el trigger de estados, ni la exclusion GiST, ni los locks reales.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.crypto import decrypt_secret, encrypt_secret
from core.utils import ensure_utc_aware
from modules.appointments.model import Appointment
from modules.notifications.model import Notification
from modules.payments.jobs import process_outbox_batch, reconcile_pending_payments
from modules.payments.model import (
    OutboxMessage,
    Payment,
    PaymentGatewayConfig,
    WebhookInbox,
)
from modules.payments.service import EVENT_PREFERENCE_EXPIRE
from tests.e2e.conftest import COLLECTOR_ID, WEBHOOK_SECRET, BREAKER_THRESHOLD, Emu
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon

pytestmark = pytest.mark.integration

ACCESS_TOKEN = "APP_USR-EMU-TIENDA-TOKEN-1"
SENA = Decimal("2500.00")
CLIENT_EMAIL = "cliente.e2e@example.com"
# Presupuesto local de una reserva publica con MP lento (lane F1-04) y la
# latencia que se le inyecta a MP: por encima del presupuesto y muy por debajo
# del timeout de httpx (20 s), asi el test no espera de mas.
PRESUPUESTO_RESERVA_S = 2.0
LATENCIA_MP_MS = 3_000


@dataclass
class Tienda:
    store_public_id: str
    store_id: str
    token: str
    admin_email: str
    service: str
    staff: str
    slot: datetime


async def _tienda(client: httpx.AsyncClient, slug: str) -> Tienda:
    """Tienda con cobros, gateway de MP apuntando al emulador y una sena fija."""
    admin_email = f"{slug}@example.com"
    store, token = await register_and_login(client, slug=slug, email=admin_email)
    flags = await client.put(
        "/stores/me/feature-flags", headers=auth_headers(token), json={"payments": True}
    )
    assert flags.status_code == 200, flags.text
    gateway = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={
            "access_token": ACCESS_TOKEN,
            "public_key": "APP_USR-PUB-EMU",
            "webhook_secret": WEBHOOK_SECRET,
        },
    )
    assert gateway.status_code == 200, gateway.text
    service = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="fixed",
        deposit_amount=2500,
    )
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff, target_date=dia)
    me = await client.get("/me", headers=auth_headers(token))
    assert me.status_code == 200, me.text
    return Tienda(
        store_public_id=store,
        store_id=cast(str, me.json()["store_id"]),
        token=token,
        admin_email=admin_email,
        service=service,
        staff=staff,
        slot=dia.replace(hour=13, minute=0, second=0, microsecond=0),  # 10:00 AR
    )


async def _reservar(client: httpx.AsyncClient, t: Tienda, key: str) -> httpx.Response:
    res = await client.post(
        "/public/appointments",
        json={
            "store_public_id": t.store_public_id,
            "service_id": t.service,
            "staff_id": t.staff,
            "starts_at": t.slot.isoformat(),
            "client_name": "Cliente E2E",
            "client_phone": "+5491155570001",
            "client_email": CLIENT_EMAIL,
            "payment_method": "mercadopago",
            "accepts_terms": True,
            "idempotency_key": key,
        },
    )
    assert res.status_code != 500, res.text
    return res


async def _turno(session: AsyncSession, public_id: str) -> Appointment:
    result = await session.execute(
        select(Appointment)
        .where(Appointment.id == public_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def _cobro(session: AsyncSession, appointment_id: str) -> Payment:
    result = await session.execute(
        select(Payment)
        .where(Payment.appointment_id == appointment_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def _outbox(session: AsyncSession, event_type: str) -> list[OutboxMessage]:
    result = await session.execute(
        select(OutboxMessage)
        .where(OutboxMessage.event_type == event_type)
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


async def _inbox(session: AsyncSession) -> list[WebhookInbox]:
    consulta = select(WebhookInbox).execution_options(populate_existing=True)
    return list((await session.execute(consulta)).scalars().all())


async def _cuenta(session: AsyncSession, model: type[Any]) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _entregar(
    client: httpx.AsyncClient, mp: Emu, payment_id: str, **options: Any
) -> httpx.Response:
    """El emulador firma el webhook; se entrega a la app por el cliente ASGI.

    La URL sale del ``notification_url`` que Shifty le dio a la preferencia,
    asi que tambien se prueba que ese link apunte al endpoint correcto.
    """
    webhook = await mp.webhook(payment_id, **options)
    url = urlsplit(webhook["url"])
    base = urlsplit(settings.PUBLIC_API_URL)
    assert (url.scheme, url.netloc) == (base.scheme, base.netloc), webhook["url"]
    path = url.path.removeprefix(base.path.rstrip("/"))
    res = await client.post(
        f"{path}?{url.query}", json=webhook["body"], headers=webhook["headers"]
    )
    assert res.status_code < 500, res.text
    return res


async def _reserva_pendiente(
    client: httpx.AsyncClient, session: AsyncSession, mp: Emu, slug: str
) -> tuple[Tienda, str, dict[str, Any]]:
    """Reserva con sena pendiente. Devuelve el id del turno, no la entidad:
    los rechazos del webhook hacen rollback de la sesion compartida y dejan
    expirada cualquier instancia que el test tuviera en la mano."""
    t = await _tienda(client, slug)
    res = await _reservar(client, t, f"{slug}-reserva-0001")
    assert res.status_code == 201, res.text
    body = cast(dict[str, Any], res.json())
    assert body["status"] == "pending_payment", body
    turno = await _turno(session, str(body["public_id"]))
    assert turno.status == "pending_payment"
    return t, turno.id, await mp.only_preference()


async def _pagar(mp: Emu, preference_id: str, **overrides: Any) -> str:
    res = await mp.pay(preference_id, **overrides)
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


# ---------------------------------------------------------------------------
# (a) Reserva con sena -> preferencia en el emulador
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_la_reserva_crea_la_preferencia_con_importe_cuenta_y_vencimiento(
    client: httpx.AsyncClient, test_session: AsyncSession, mp: Emu
) -> None:
    t = await _tienda(client, "e2e-preferencia")
    res = await _reservar(client, t, "e2e-preferencia-0001")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "pending_payment"
    assert body["payment_amount"] == float(SENA)

    turno = await _turno(test_session, body["public_id"])
    cobro = await _cobro(test_session, turno.id)
    pref = await mp.only_preference()

    # Importe, moneda y referencia: lo que despues valida el webhook.
    [item] = pref["items"]
    assert Decimal(str(item["unit_price"])) == SENA == cobro.amount
    assert item["currency_id"] == "ARS" and item["quantity"] == 1
    # La del link: <turno>:<link_ref> (perf/f4-pay).
    assert pref["external_reference"] == cobro.current_external_reference
    assert pref["external_reference"].split(":")[0] == turno.id
    assert pref["metadata"] == {
        "appointment_id": turno.id,
        "store_id": t.store_id,
        "store_public_id": t.store_public_id,
        "payment_id": cobro.id,
    }
    # Cuenta: la preferencia se pidio con el token de la tienda.
    [llamada] = await mp.calls("/checkout/preferences", "POST")
    assert llamada["token"] == ACCESS_TOKEN
    assert pref["collector_id"] == int(COLLECTOR_ID)
    # Webhook: vuelve al endpoint de Shifty con la tienda en la query.
    assert pref["notification_url"] == (
        f"{settings.PUBLIC_API_URL}/payments/webhooks/mercadopago"
        f"?store_id={t.store_public_id}"
    )
    # Vencimiento: el checkout muere junto con la retencion del turno.
    assert pref["expires"] is True
    vence = datetime.fromisoformat(pref["expiration_date_to"])
    # En Postgres (timestamptz) sale con offset; en SQLite el refresh del alta
    # devuelve un datetime naive y el ISO sale sin offset: se lee como UTC.
    vence = ensure_utc_aware(vence)
    assert turno.expires_at is not None
    assert abs(vence - ensure_utc_aware(turno.expires_at)) < timedelta(seconds=1)
    esperado = datetime.now(timezone.utc) + timedelta(
        minutes=settings.PAYMENT_HOLD_MINUTES
    )
    assert abs(vence - esperado) < timedelta(minutes=1)

    # Shifty sello el link real del emulador.
    assert cobro.preference_id == pref["id"]
    assert cobro.payment_link == pref["init_point"] == body["payment_link"]
    assert cobro.status == "pending"
    assert turno.status == "pending_payment"


# ---------------------------------------------------------------------------
# (b) Pago + webhook firmado -> cobro acreditado y turno confirmado
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b_el_pago_con_webhook_firmado_confirma_el_turno_y_avisa(
    client: httpx.AsyncClient, test_session: AsyncSession, mp: Emu, buzon: Buzon
) -> None:
    t, turno_id, pref = await _reserva_pendiente(
        client, test_session, mp, "e2e-webhook"
    )
    mp_payment_id = await _pagar(mp, pref["id"])

    res = await _entregar(client, mp, mp_payment_id)
    assert res.status_code == 200, res.text
    assert res.json() == {"received": True, "applied": True}

    cobro = await _cobro(test_session, turno_id)
    assert cobro.status == "approved"
    assert cobro.external_payment_id == mp_payment_id
    assert (await _turno(test_session, turno_id)).status == "confirmed"
    [inbox] = await _inbox(test_session)
    assert inbox.processed_at is not None and inbox.error is None
    assert len(await _outbox(test_session, "payment.approved")) == 1

    # El handler le pregunto a MP por el pago, sin transaccion abierta
    # (AUD2-B2-08).
    [consulta] = await mp.calls(f"/v1/payments/{mp_payment_id}", "GET")
    assert consulta["token"] == ACCESS_TOKEN
    assert consulta["in_tx"] is False

    # El outbox convierte el aviso en notificacion + mail al dueno + "turno
    # confirmado" al cliente. Afuera el "reserva registrada" del alta.
    buzon.enviados.clear()
    resultado = await process_outbox_batch(test_session)
    assert resultado["failed"] == 0, resultado
    avisos = (
        (
            await test_session.execute(
                select(Notification).where(Notification.type == "payment.approved")
            )
        )
        .scalars()
        .all()
    )
    assert len(avisos) == 1
    mails = {to: asunto for to, asunto, _cuerpo in buzon.enviados}
    assert t.admin_email in mails, buzon.enviados
    assert mails.get(CLIENT_EMAIL, "").startswith("Turno confirmado"), mails


# ---------------------------------------------------------------------------
# (c) Webhook duplicado -> idempotente
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c_el_mismo_evento_dos_veces_no_tiene_segundo_efecto(
    client: httpx.AsyncClient, test_session: AsyncSession, mp: Emu
) -> None:
    _t, turno_id, pref = await _reserva_pendiente(
        client, test_session, mp, "e2e-duplicado"
    )
    mp_payment_id = await _pagar(mp, pref["id"])

    primero = await _entregar(client, mp, mp_payment_id, event_id="evt-e2e-1")
    assert primero.json()["applied"] is True
    # MP reintenta: mismo evento, otro request id y otra firma.
    segundo = await _entregar(client, mp, mp_payment_id, event_id="evt-e2e-1")
    assert segundo.status_code == 200, segundo.text
    assert segundo.json() == {"status": "already_processed"}

    assert len(await _inbox(test_session)) == 1
    assert len(await _outbox(test_session, "payment.approved")) == 1
    cobro = await _cobro(test_session, turno_id)
    assert cobro.status == "approved"
    assert (await _turno(test_session, turno_id)).status == "confirmed"


# ---------------------------------------------------------------------------
# (d) Importe o cuenta que no coinciden -> rechazo sin 5xx, inbox sin sellar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pago", "motivo"),
    [
        ({"amount": 100.0}, "importe"),
        ({"collector_id": "999999999"}, "otra cuenta"),
    ],
    ids=["importe", "collector"],
)
async def test_d_un_pago_inconsistente_se_rechaza_y_queda_para_reintento(
    client: httpx.AsyncClient,
    test_session: AsyncSession,
    mp: Emu,
    pago: dict[str, Any],
    motivo: str,
) -> None:
    t, turno_id, pref = await _reserva_pendiente(
        client, test_session, mp, "e2e-inconsistente"
    )
    # El collector solo se valida contra una cuenta conocida (OAuth).
    await test_session.execute(
        update(PaymentGatewayConfig)
        .where(PaymentGatewayConfig.store_id == t.store_id)
        .values(oauth_user_id=COLLECTOR_ID)
    )
    await test_session.commit()
    mp_payment_id = await _pagar(mp, pref["id"], **pago)

    res = await _entregar(client, mp, mp_payment_id)
    assert res.status_code == 200, res.text
    assert res.json()["applied"] is False

    [inbox] = await _inbox(test_session)
    assert inbox.processed_at is None, "un rechazo no puede sellar el evento"
    assert inbox.attempts == 1
    assert motivo in (inbox.error or ""), inbox.error
    cobro = await _cobro(test_session, turno_id)
    assert cobro.status == "pending"
    assert cobro.external_payment_id is None
    assert (await _turno(test_session, turno_id)).status == "pending_payment"
    assert await _outbox(test_session, "payment.approved") == []


# ---------------------------------------------------------------------------
# (e) Firma invalida o vencida -> 400/401 y nada cambia
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("opciones", "esperado"),
    [
        ({"tamper": True}, 401),
        ({"secret": "otro-secreto"}, 401),
        ({"ts_offset_seconds": -3600}, 401),
        ({"ts_offset_seconds": 3600}, 401),
        ({"sin_headers": True}, 400),
    ],
    ids=["firma-alterada", "otro-secreto", "ts-viejo", "ts-futuro", "sin-headers"],
)
async def test_e_un_webhook_sin_firma_valida_no_toca_nada(
    client: httpx.AsyncClient,
    test_session: AsyncSession,
    mp: Emu,
    opciones: dict[str, Any],
    esperado: int,
) -> None:
    _t, turno_id, pref = await _reserva_pendiente(client, test_session, mp, "e2e-firma")
    mp_payment_id = await _pagar(mp, pref["id"])

    sin_headers = opciones.pop("sin_headers", False)
    webhook = await mp.webhook(mp_payment_id, **opciones)
    url = urlsplit(webhook["url"])
    res = await client.post(
        f"{url.path}?{url.query}",
        json=webhook["body"],
        headers={} if sin_headers else webhook["headers"],
    )
    assert res.status_code == esperado, res.text

    assert await _inbox(test_session) == []
    assert (await _cobro(test_session, turno_id)).status == "pending"
    assert (await _turno(test_session, turno_id)).status == "pending_payment"
    # La firma se valida ANTES de salir a MP: un webhook falso no gasta
    # requests a la API con el token de la tienda.
    assert await mp.calls(f"/v1/payments/{mp_payment_id}") == []


# ---------------------------------------------------------------------------
# (f) Reembolso desde el panel: se registra, no se ejecuta en MP (B2-05)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f_el_reembolso_del_panel_se_registra_sin_llamar_a_mp(
    client: httpx.AsyncClient, test_session: AsyncSession, mp: Emu
) -> None:
    t, turno_id, pref = await _reserva_pendiente(
        client, test_session, mp, "e2e-reembolso"
    )
    mp_payment_id = await _pagar(mp, pref["id"])
    await _entregar(client, mp, mp_payment_id)
    cobro = await _cobro(test_session, turno_id)
    assert cobro.status == "approved"

    sin_manual = await client.post(
        f"/payments/{cobro.id}/refund",
        headers=auth_headers(t.token),
        json={"reason": "cliente cancelo"},
    )
    assert 400 <= sin_manual.status_code < 500, sin_manual.text
    assert (await _cobro(test_session, turno_id)).status == "approved"

    registrado = await client.post(
        f"/payments/{cobro.id}/refund",
        headers=auth_headers(t.token),
        json={"reason": "devuelto desde MP", "manual": True},
    )
    assert registrado.status_code == 200, registrado.text
    assert registrado.json()["status"] == "refunded"

    assert (await _cobro(test_session, turno_id)).status == "refunded"
    # Decision escrita: un turno confirmado sigue confirmado tras el reembolso.
    assert (await _turno(test_session, turno_id)).status == "confirmed"
    assert len(await _outbox(test_session, "payment.refunded")) == 1
    estado = await mp.state()
    assert estado["refunds"] == []
    assert [c for c in estado["calls"] if c["path"].endswith("/refunds")] == []
    assert estado["payments"][mp_payment_id]["status"] == "approved"


# ---------------------------------------------------------------------------
# (g) Liberar -> outbox payment.preference.expire -> job vence el link en MP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g_liberar_vence_el_link_en_mp_desde_el_outbox_en_dos_fases(
    client: httpx.AsyncClient, test_session: AsyncSession, mp: Emu
) -> None:
    t, turno_id, pref = await _reserva_pendiente(
        client, test_session, mp, "e2e-vencimiento"
    )

    liberado = await client.patch(
        f"/appointments/{turno_id}/release", headers=auth_headers(t.token)
    )
    assert liberado.status_code == 200, liberado.text
    assert liberado.json()["status"] == "expired"
    # Liberar no sale a MP (B1-04): deja el evento en el outbox.
    assert await mp.calls(f"/checkout/preferences/{pref['id']}", "PUT") == []
    [evento] = await _outbox(test_session, EVENT_PREFERENCE_EXPIRE)
    assert evento.processed_at is None
    assert evento.payload["preference_id"] == pref["id"]
    assert (await _cobro(test_session, turno_id)).status == "expired"

    resultado = await process_outbox_batch(test_session)
    assert resultado["failed"] == 0, resultado

    [vencimiento] = await mp.calls(f"/checkout/preferences/{pref['id']}", "PUT")
    assert vencimiento["token"] == ACCESS_TOKEN
    assert vencimiento["json"]["expires"] is True
    assert vencimiento["in_tx"] is False, "MP con transaccion abierta (regla 5)"
    [evento] = await _outbox(test_session, EVENT_PREFERENCE_EXPIRE)
    assert evento.processed_at is not None and evento.error is None
    # El checkout quedo muerto de verdad: el cliente ya no puede pagarlo.
    tarde = await mp.pay(pref["id"])
    assert tarde.status_code == 409, tarde.text


# ---------------------------------------------------------------------------
# (h) OAuth: 401 una vez -> refresh -> reintento con el token nuevo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h_un_401_refresca_el_token_oauth_y_reintenta(
    client: httpx.AsyncClient, test_session: AsyncSession, mp: Emu
) -> None:
    t = await _tienda(client, "e2e-oauth")
    await test_session.execute(
        update(PaymentGatewayConfig)
        .where(PaymentGatewayConfig.store_id == t.store_id)
        .values(
            connection_mode="oauth",
            oauth_user_id=COLLECTOR_ID,
            encrypted_refresh_token=encrypt_secret("TG-SEMILLA-REFRESH"),
        )
    )
    await test_session.commit()
    await mp.fault(unauthorized_once=True)

    res = await _reservar(client, t, "e2e-oauth-0001")
    assert res.status_code == 201, res.text

    llamadas = [
        (c["method"], c["path"], c["token"]) for c in (await mp.state())["calls"]
    ]
    assert [ruta for _m, ruta, _tok in llamadas] == [
        "/checkout/preferences",
        "/oauth/token",
        "/checkout/preferences",
    ], llamadas
    [refresh] = await mp.calls("/oauth/token", "POST")
    assert refresh["json"]["grant_type"] == "refresh_token"
    assert refresh["json"]["refresh_token"] == "TG-SEMILLA-REFRESH"
    token_nuevo = llamadas[2][2]
    assert token_nuevo != ACCESS_TOKEN
    assert ACCESS_TOKEN in (await mp.state())["revoked_tokens"]

    config = (
        await test_session.execute(
            select(PaymentGatewayConfig)
            .where(PaymentGatewayConfig.store_id == t.store_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert decrypt_secret(config.encrypted_access_token) == token_nuevo
    refresh_nuevo = decrypt_secret(config.encrypted_refresh_token) or ""
    assert refresh_nuevo.startswith("TG-EMU-"), "MP rota el refresh token"

    # Y el resto del ciclo sigue con el token nuevo.
    pref = await mp.only_preference()
    mp_payment_id = await _pagar(mp, pref["id"])
    webhook = await _entregar(client, mp, mp_payment_id)
    assert webhook.json()["applied"] is True
    [consulta] = await mp.calls(f"/v1/payments/{mp_payment_id}", "GET")
    assert consulta["token"] == token_nuevo


# ---------------------------------------------------------------------------
# (i) Conciliacion: pago acreditado sin webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_i_la_conciliacion_recupera_un_pago_sin_webhook(
    client: httpx.AsyncClient,
    test_session: AsyncSession,
    mp: Emu,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # F1-20: sin edad minima, el cobro recien creado ya es conciliable.
    monkeypatch.setattr(settings, "RECONCILIATION_MIN_AGE_MINUTES", 0)
    _t, turno_id, pref = await _reserva_pendiente(
        client, test_session, mp, "e2e-conciliacion"
    )
    mp_payment_id = await _pagar(mp, pref["id"])
    assert (await _cobro(test_session, turno_id)).status == "pending"

    resultado = await reconcile_pending_payments(test_session)
    assert resultado == {"reconciled": 1, "failed": 0, "inspected": 1}, resultado

    [busqueda] = await mp.calls("/v1/payments/search", "GET")
    referencia = (await _cobro(test_session, turno_id)).current_external_reference
    assert f"external_reference={referencia.replace(':', '%3A')}" in busqueda["query"]
    assert busqueda["in_tx"] is False, "MP con transaccion abierta (regla 5)"
    cobro = await _cobro(test_session, turno_id)
    assert cobro.status == "approved"
    assert cobro.external_payment_id == mp_payment_id
    assert (await _turno(test_session, turno_id)).status == "confirmed"
    assert len(await _outbox(test_session, "payment.approved")) == 1


# ---------------------------------------------------------------------------
# (j) MP lento -> la reserva responde dentro del presupuesto y compensa
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_j_con_mp_lento_la_reserva_corta_en_presupuesto_y_compensa(
    client: httpx.AsyncClient,
    test_session: AsyncSession,
    mp: Emu,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Presupuesto de MP de la reserva (F1-04) por debajo del limite local del
    # test: el de produccion (8 s) no puede bajar de los 1-2 s que tarda una
    # preferencia sana.
    monkeypatch.setattr(settings, "MERCADOPAGO_REQUEST_BUDGET_SECONDS", 1.5)
    t = await _tienda(client, "e2e-latencia")
    await mp.fault(latency_ms=LATENCIA_MP_MS)

    inicio = time.monotonic()
    res = await _reservar(client, t, "e2e-latencia-0001")
    duracion = time.monotonic() - inicio

    assert duracion < PRESUPUESTO_RESERVA_S, f"la reserva tardo {duracion:.1f} s"
    assert res.status_code in (502, 503), res.text
    assert await _cuenta(test_session, Appointment) == 0
    assert await _cuenta(test_session, Payment) == 0


# ---------------------------------------------------------------------------
# (k) Circuit breaker: se abre tras N fallas, la reserva compensa, se recupera
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_k_el_breaker_se_abre_la_reserva_compensa_y_despues_se_recupera(
    client: httpx.AsyncClient, test_session: AsyncSession, mp: Emu
) -> None:
    t = await _tienda(client, "e2e-breaker")
    await mp.fault(error_rate=1.0, error_status=500)

    # 502 y 503 son respuestas disenadas (proveedor caido), no errores
    # propios: lo que no puede aparecer es un 500.
    for intento in range(BREAKER_THRESHOLD):
        res = await _reservar(client, t, f"e2e-breaker-{intento:04d}")
        assert res.status_code == 502, res.text
        assert res.json()["error_code"] == "PAYMENT_LINK_CREATION_FAILED"
        # Compensacion: ni turno ni cobro colgados, el horario sigue libre.
        assert await _cuenta(test_session, Appointment) == 0
        assert await _cuenta(test_session, Payment) == 0
    assert len(await mp.calls("/checkout/preferences", "POST")) == BREAKER_THRESHOLD

    abierto = await _reservar(client, t, "e2e-breaker-abierto")
    assert abierto.status_code == 503, abierto.text
    assert abierto.json()["error_code"] == "PAYMENT_PROVIDER_UNAVAILABLE"
    # Con el breaker abierto el backend ni siquiera llama a MP.
    assert len(await mp.calls("/checkout/preferences", "POST")) == BREAKER_THRESHOLD
    assert await _cuenta(test_session, Appointment) == 0

    # MP vuelve: pasado el recovery, la sonda half-open cierra el breaker.
    await mp.fault(error_rate=0.0)
    await asyncio.sleep(1.2)
    recuperado = await _reservar(client, t, "e2e-breaker-recuperado")
    assert recuperado.status_code == 201, recuperado.text
    assert await _cuenta(test_session, Appointment) == 1


# ---------------------------------------------------------------------------
# (l) La reserva sale a MP sin transaccion abierta (defecto encontrado aca)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l_la_reserva_llama_a_mp_sin_transaccion_abierta(
    client: httpx.AsyncClient, test_session: AsyncSession, mp: Emu
) -> None:
    t = await _tienda(client, "e2e-sin-transaccion")
    res = await _reservar(client, t, "e2e-sin-transaccion-0001")
    assert res.status_code == 201, res.text
    [preferencia] = await mp.calls("/checkout/preferences", "POST")
    assert preferencia["in_tx"] is False, "MP con la conexion del pool tomada"


# ---------------------------------------------------------------------------
# Referencia propia por link (revision de perf/f4-pay, 2026-09-25)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_pago_no_trae_preference_id_y_se_concilia_por_la_referencia_del_link(
    client: httpx.AsyncClient,
    test_session: AsyncSession,
    mp: Emu,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Como MP: el pago no trae ``preference_id``. Con el nonce por link
    prendido, la preferencia lleva ``<turno>:<link_ref>`` y la conciliacion
    busca por esa referencia (la del link vigente), no por el turno solo."""
    monkeypatch.setattr(settings, "RECONCILIATION_MIN_AGE_MINUTES", 0)
    monkeypatch.setattr(settings, "MERCADOPAGO_LINK_REF_ENABLED", True)
    _t, turno_id, pref = await _reserva_pendiente(
        client, test_session, mp, "e2e-referencia-link"
    )
    cobro = await _cobro(test_session, turno_id)
    referencia = cobro.current_external_reference
    assert cobro.link_ref and referencia == f"{turno_id}:{cobro.link_ref}"
    assert pref["external_reference"] == referencia

    mp_payment_id = await _pagar(mp, pref["id"])
    publico = await mp.http.get(
        f"/v1/payments/{mp_payment_id}",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
    )
    assert publico.status_code == 200, publico.text
    assert "preference_id" not in publico.json()
    assert publico.json()["external_reference"] == referencia

    resultado = await reconcile_pending_payments(test_session)

    assert resultado["reconciled"] == 1, resultado
    [busqueda] = await mp.calls("/v1/payments/search", "GET")
    assert busqueda["query"].split("external_reference=")[1].split("&")[0] == (
        referencia.replace(":", "%3A")
    )
    assert (await _cobro(test_session, turno_id)).status == "approved"
