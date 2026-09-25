"""Rafaga: el personal cancela un turno con cobro vivo mientras llega el pago.

Decision de Mateo (2026-09-25, D2): cancelar desde el panel un turno con
cobro vivo vence el cobro en la misma transaccion. Esto es lo que SQLite no
puede probar: N cancelaciones del profesional y el webhook de Mercado Pago
aprobando el MISMO turno a la vez, con una sesion por request.

Los dos caminos lockean en el mismo orden, turno -> pago (regla 7: el webhook
busca el cobro sin lock y despues lockea turno y pago, F1-18), asi que se
serializan sobre la fila del turno y no hay deadlock. Lo que el codigo
garantiza, sea cual sea el orden, y lo que se fija aca:

- cero 5xx; el webhook se aplica (200); UNA cancelacion responde 200 y las
  demas 409 ``APPOINTMENT_ALREADY_CANCELLED`` (CLAUDE.md §4, "1 exito, N-1
  conflictos"; revision de perf/f4-pay): no republican el cupo ni vencen
  otra vez.
- estado final: turno ``cancelled`` y pago ``approved``. La plata que entro
  queda registrada para poder devolverla: el grafo del pago permite
  ``expired -> approved`` a proposito (un pago real que llega tarde no se
  pierde) y el webhook no revive un turno ya soltado (S-16).
- UN solo aviso al dueno sobre esa plata, y el que corresponde al orden:
    * gano la cancelacion: el cobro se vencio (hay un
      ``payment.preference.expire``) y el aviso es
      ``payment.received_on_released_appointment`` (hay que devolverla);
    * gano el webhook: el turno se confirmo, la cancelacion encontro el pago
      ya acreditado y no lo toco (fuera de D2, como hasta hoy): no hay
      vencimiento y el aviso es ``payment.approved``.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
from core.config import settings
import modules.payments.service as payments_service
from modules.notifications.model import NotificationType
from modules.payments.service import EVENT_PREFERENCE_EXPIRE
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    webhook_signature_headers,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
)
from tests.postgres.conftest import PASSWORD, auth_headers, register_and_login

pytestmark = pytest.mark.postgres

TURNOS = 3
CANCELACIONES = 4


class _MercadoPago:
    """Doble de MP: una preferencia distinta por cobro y el pago aprobado."""

    def __init__(self) -> None:
        self._n = itertools.count(1)
        self.remotos: dict[str, dict[str, Any]] = {}
        # (preferencia, external_reference) de cada link creado.
        self.creadas: list[tuple[str, str]] = []

    async def __call__(
        self,
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if method == "POST" and path == "/checkout/preferences":
            n = next(self._n)
            assert json_body is not None
            self.creadas.append(
                (f"pref-d2-pg-{n}", str(json_body["external_reference"]))
            )
            return {
                "id": f"pref-d2-pg-{n}",
                "init_point": f"https://www.mercadopago.com/checkout?pref=d2-{n}",
            }
        if path.startswith("/v1/payments/"):
            return self.remotos[path.rsplit("/", 1)[1]]
        return {}


async def _profesional(client: AsyncClient, admin: str) -> str:
    alta = await client.post(
        "/users/",
        headers=auth_headers(admin),
        json={
            "email": "pro-d2-pg@demo.com",
            "password": PASSWORD,
            "first_name": "Pro",
            "last_name": "Rafaga",
            "role": "staff",
        },
    )
    assert alta.status_code == 201, alta.text
    login = await client.post(
        "/auth/login", json={"email": "pro-d2-pg@demo.com", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


async def _cobros(owner_engine: AsyncEngine) -> dict[str, dict[str, Any]]:
    async with owner_engine.connect() as conn:
        filas = await conn.execute(
            text(
                "select a.id, a.status, p.id, p.status, p.preference_id, p.amount "
                "from appointments a join payments p on p.appointment_id = a.id"
            )
        )
        return {
            str(f[0]): {
                "turno": f[1],
                "pago_id": str(f[2]),
                "pago": f[3],
                "preferencia": f[4],
                "importe": float(f[5]),
            }
            for f in filas.all()
        }


async def _eventos(owner_engine: AsyncEngine) -> list[tuple[str, dict[str, Any]]]:
    async with owner_engine.connect() as conn:
        filas = await conn.execute(
            text("select event_type, payload::text from outbox_messages")
        )
        return [(str(f[0]), json.loads(f[1])) for f in filas.all()]


@pytest.mark.asyncio
@pytest.mark.parametrize("orden", ["rafaga", "webhook_primero"])
async def test_cancelar_con_cobro_vivo_contra_el_pago_aprobado_queda_consistente(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    orden: str,
) -> None:
    """``rafaga``: todo a la vez (en las corridas medidas gano siempre la
    cancelacion: el webhook consulta a MP y busca el cobro antes de pedir el
    lock). ``webhook_primero``: el pago entra y recien despues llega la rafaga
    de cancelaciones, para fijar la otra rama de forma determinista."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    mp = _MercadoPago()
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    store, admin = await register_and_login(
        client, app_sessions, slug="d2-pg-rafaga", email="d2-pg-rafaga@demo.com"
    )
    # Activar cobros exige la politica de sena publicada (DEPOSIT_POLICY_REQUIRED).
    politica = await client.patch(
        "/stores/me",
        headers=auth_headers(admin),
        json={"deposit_policy": "La sena se descuenta del total."},
    )
    assert politica.status_code == 200, politica.text
    await _enable_payments(client, admin)
    await _configure_gateway(client, admin)
    service = await create_service(
        client,
        admin,
        deposit_mode="required",
        deposit_type="fixed",
        deposit_amount=2500,
    )
    staff = await create_staff(client, admin, service, email="staff-d2-pg@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, admin, staff, target_date=dia)
    profesional = await _profesional(client, admin)

    turnos: list[str] = []
    for i in range(TURNOS):
        reserva = await client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": service,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=10 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": f"Cliente Rafaga {i}",
                "client_phone": f"+54911557{i:05d}",
                "accepts_terms": True,
                "payment_method": "mercadopago",
                "idempotency_key": f"d2-pg-reserva-{i:04d}",
            },
        )
        assert reserva.status_code == 201, reserva.text
        assert reserva.json()["status"] == "pending_payment"
        turnos.append(str(reserva.json()["public_id"]))

    antes = await _cobros(owner_engine)
    for i, turno in enumerate(turnos):
        cobro = antes[turno]
        assert cobro["pago"] == "pending", cobro
        mp.remotos[f"mp-d2-{i}"] = {
            "id": f"mp-d2-{i}",
            "status": "approved",
            # La del link de su preferencia (<turno>:<link_ref>), como MP.
            "external_reference": dict(mp.creadas)[cobro["preferencia"]],
            "preference_id": cobro["preferencia"],
            "transaction_amount": cobro["importe"],
            "currency_id": "ARS",
        }

    def webhook(i: int) -> Any:
        return client.post(
            f"/payments/webhooks/mercadopago?store_id={store}",
            json={"id": f"evt-d2-{i}", "type": "payment", "data": {"id": f"mp-d2-{i}"}},
            headers=webhook_signature_headers(
                secret="secret-demo",
                data_id=f"mp-d2-{i}",
                request_id=f"req-d2-{i}",
                ts="0",
            ),
        )

    def cancelar(turno: str) -> Any:
        return client.patch(
            f"/appointments/{turno}/cancel", headers=auth_headers(profesional)
        )

    pedidos: list[tuple[str, str]] = []
    llamadas: list[Any] = []
    respuestas: list[Response] = []
    for i, turno in enumerate(turnos):
        if orden == "webhook_primero":
            pedidos.append((turno, "webhook"))
            respuestas.append(await webhook(i))
        else:
            pedidos.append((turno, "webhook"))
            llamadas.append(webhook(i))
        for _ in range(CANCELACIONES):
            pedidos.append((turno, "cancelar"))
            llamadas.append(cancelar(turno))
    respuestas.extend(await asyncio.gather(*llamadas))
    if orden == "webhook_primero":
        # Los webhooks van primero en ``respuestas``: se reordena igual que
        # ``pedidos`` (webhook, cancelaciones) por turno.
        webhooks, rafaga = respuestas[:TURNOS], respuestas[TURNOS:]
        respuestas = []
        for i in range(TURNOS):
            respuestas.append(webhooks[i])
            respuestas.extend(rafaga[i * CANCELACIONES : (i + 1) * CANCELACIONES])

    assert all(r.status_code < 500 for r in respuestas), [
        (r.status_code, r.text[:200]) for r in respuestas if r.status_code >= 500
    ]
    despues = await _cobros(owner_engine)
    eventos = await _eventos(owner_engine)
    for turno in turnos:
        propias = [
            r for (t, _tipo), r in zip(pedidos, respuestas, strict=True) if t == turno
        ]
        tipos = [tipo for (t, tipo) in pedidos if t == turno]
        cancelaciones = sorted(
            r.status_code
            for r, tipo in zip(propias, tipos, strict=True)
            if tipo == "cancelar"
        )
        (webhook_res,) = [
            r for r, tipo in zip(propias, tipos, strict=True) if tipo == "webhook"
        ]
        # Una gana; las demas encuentran el turno ya cancelado bajo el lock.
        assert cancelaciones == [200] + [409] * (CANCELACIONES - 1), cancelaciones
        codigos = {
            r.json()["error_code"]
            for r, tipo in zip(propias, tipos, strict=True)
            if tipo == "cancelar" and r.status_code == 409
        }
        assert codigos == {"APPOINTMENT_ALREADY_CANCELLED"}, codigos
        assert webhook_res.status_code == 200, webhook_res.text
        cuerpo = webhook_res.json()
        assert cuerpo.get("data", cuerpo)["applied"] is True, cuerpo

        final = despues[turno]
        assert final["turno"] == "cancelled", final
        assert final["pago"] == "approved", final

        vencimientos = [
            p
            for e, p in eventos
            if e == EVENT_PREFERENCE_EXPIRE and p.get("appointment_id") == turno
        ]
        avisos = [
            e
            for e, p in eventos
            if p.get("payment_id") == final["pago_id"]
            and e
            in {
                NotificationType.PAYMENT_APPROVED.value,
                NotificationType.PAYMENT_ON_RELEASED_APPOINTMENT.value,
            }
        ]
        assert len(avisos) == 1, (turno, avisos)
        if orden == "webhook_primero":
            assert vencimientos == [], vencimientos
        if vencimientos:
            # Gano la cancelacion: el cobro se vencio y la plata llego tarde.
            assert len(vencimientos) == 1, vencimientos
            assert vencimientos[0]["preference_id"] == final["preferencia"]
            assert avisos == [NotificationType.PAYMENT_ON_RELEASED_APPOINTMENT.value]
        else:
            # Gano el webhook: el pago acreditado no se vence al cancelar.
            assert avisos == [NotificationType.PAYMENT_APPROVED.value]


# ---------------------------------------------------------------------------
# Link del panel contra cancelar (revision de perf/f4-pay, 2026-09-25, #3)
# ---------------------------------------------------------------------------

TELEFONO_CLIENTE = "+5491155577001"
CARRERAS = 4


class _MercadoPagoLento:
    """Crea preferencias despacio (ensancha la ventana de la fase 2) y anota
    de que turno es cada una (``external_reference``)."""

    def __init__(self) -> None:
        self._n = itertools.count(1)
        self.creadas: list[tuple[str, str]] = []

    async def __call__(
        self,
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert method == "POST" and path == "/checkout/preferences", (method, path)
        await asyncio.sleep(0.2)
        preferencia = f"pref-carrera-{next(self._n)}"
        assert json_body is not None
        self.creadas.append((preferencia, str(json_body["external_reference"])))
        return {
            "id": preferencia,
            "init_point": f"https://www.mercadopago.com/checkout?pref={preferencia}",
        }


async def _estado_de_turnos_y_cobros(
    owner_engine: AsyncEngine,
) -> dict[str, tuple[str, list[tuple[str, str | None]]]]:
    async with owner_engine.connect() as conn:
        turnos = await conn.execute(text("select id, status from appointments"))
        cobros = await conn.execute(
            text("select appointment_id, status, preference_id from payments")
        )
        por_turno: dict[str, tuple[str, list[tuple[str, str | None]]]] = {
            str(t[0]): (str(t[1]), []) for t in turnos.all()
        }
        for turno, estado, preferencia in cobros.all():
            por_turno[str(turno)][1].append((str(estado), preferencia))
        return por_turno


@pytest.mark.asyncio
@pytest.mark.parametrize("quien", ["cliente", "personal"])
async def test_link_del_panel_contra_cancelar_nunca_deja_un_link_vivo_cancelado(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    quien: str,
) -> None:
    """``POST /payments/preferences/{id}`` y la cancelacion del mismo turno a
    la vez (cliente por el portal o profesional por el panel).

    Lo que se garantiza en cualquier orden: cero 5xx y NUNCA un turno
    cancelado con un cobro vivo; todo link creado en MP para un turno que
    termino cancelado tiene su ``payment.preference.expire`` publicado. Con el
    cliente, gana uno solo: o cancela (y el link responde 409
    ``APPOINTMENT_NOT_PAYABLE`` sin crear cobro) o el link queda y el cliente
    recibe 409 ``PAYMENT_APPOINTMENT_REQUIRES_RELEASE`` (D1).
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    mp = _MercadoPagoLento()
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    slug = f"link-carrera-{quien}"
    store, admin = await register_and_login(
        client, app_sessions, slug=slug, email=f"{slug}@demo.com"
    )
    politica = await client.patch(
        "/stores/me",
        headers=auth_headers(admin),
        json={"deposit_policy": "La sena se descuenta del total."},
    )
    assert politica.status_code == 200, politica.text
    await _enable_payments(client, admin)
    await _configure_gateway(client, admin)
    service = await create_service(client, admin)
    staff = await create_staff(client, admin, service, email=f"staff-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, admin, staff, target_date=dia)

    turnos: list[str] = []
    for i in range(CARRERAS):
        reserva = await client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": service,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=10 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": "Cliente Carrera",
                "client_email": f"cliente-{slug}@example.com",
                "client_phone": TELEFONO_CLIENTE,
                "accepts_terms": True,
                "idempotency_key": f"{slug}-{i:04d}",
            },
        )
        assert reserva.status_code == 201, reserva.text
        turnos.append(str(reserva.json()["public_id"]))

    if quien == "cliente":
        pedido = await client.post(
            "/public/otp/request",
            json={
                "store_public_id": store,
                "phone": TELEFONO_CLIENTE,
                "channel": "whatsapp",
            },
        )
        assert pedido.status_code == 200, pedido.text
        verificado = await client.post(
            "/public/otp/verify",
            json={
                "store_public_id": store,
                "phone": TELEFONO_CLIENTE,
                "code": pedido.json()["debug_code"],
            },
        )
        assert verificado.status_code == 200, verificado.text

        def cancelar(turno: str) -> Any:
            return client.patch(
                f"/public/client/appointments/{turno}/cancel",
                json={"phone": TELEFONO_CLIENTE},
            )

    else:
        profesional = await _profesional(client, admin)

        def cancelar(turno: str) -> Any:
            return client.patch(
                f"/appointments/{turno}/cancel", headers=auth_headers(profesional)
            )

    llamadas: list[Any] = []
    for turno in turnos:
        llamadas.append(
            client.post(f"/payments/preferences/{turno}", headers=auth_headers(admin))
        )
        llamadas.append(cancelar(turno))
    respuestas: list[Response] = await asyncio.gather(*llamadas)

    assert all(r.status_code < 500 for r in respuestas), [
        (r.status_code, r.text[:200]) for r in respuestas if r.status_code >= 500
    ]
    estado = await _estado_de_turnos_y_cobros(owner_engine)
    vencidas = {
        p["preference_id"]
        for e, p in await _eventos(owner_engine)
        if e == EVENT_PREFERENCE_EXPIRE
    }
    for i, turno in enumerate(turnos):
        link, cancelacion = respuestas[2 * i], respuestas[2 * i + 1]
        turno_estado, cobros = estado[turno]
        assert link.status_code in {200, 409}, link.text
        if link.status_code == 409:
            assert link.json()["error_code"] == "APPOINTMENT_NOT_PAYABLE", link.text
        if turno_estado == "cancelled":
            vivos = [c for c in cobros if c[0] in {"pending", "rejected"}]
            assert vivos == [], (turno, cobros)
            creadas = [p for p, t in mp.creadas if t == turno]
            assert set(creadas) <= vencidas, (turno, creadas, vencidas)
        if quien == "cliente":
            codigos = sorted([link.status_code, cancelacion.status_code])
            assert codigos == [200, 409], (turno, link.text, cancelacion.text)
            if cancelacion.status_code == 200:
                assert cobros == [], (turno, cobros)
            else:
                assert (
                    cancelacion.json()["error_code"]
                    == "PAYMENT_APPOINTMENT_REQUIRES_RELEASE"
                )
                assert turno_estado != "cancelled"
        else:
            assert cancelacion.status_code == 200, cancelacion.text
            assert turno_estado == "cancelled"


# ---------------------------------------------------------------------------
# Bloqueo contra el pago (RECHAZO de la revision de perf/f4-pay, 2026-09-25)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bloqueo_sobre_turnos_con_link_contra_el_pago_aprobado(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un bloqueo con ``cancel_affected`` que cubre turnos confirmados con link
    del panel, a la vez que el webhook aprueba esos links.

    Orden de locks: el bloqueo toma profesional -> turnos -> pagos; el webhook
    turno -> pago. Se serializan sobre la fila del turno, sin deadlock. Lo que
    se fija, sea cual sea el orden, por turno:
    - gano el bloqueo: turno ``cancelled``, el cobro se vencio (hay un
      ``payment.preference.expire`` de su link) y el pago que llega despues
      queda ``approved`` con el aviso de plata sobre un turno liberado;
    - gano el webhook: pago ``approved``, turno ``confirmed``; el bloqueo lo
      saltea (``has_deposit``) y no hay vencimiento; aviso ``payment.approved``.
    Nunca un turno cancelado con un cobro vivo, cero 5xx, un solo aviso.
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    mp = _MercadoPago()
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    store, admin = await register_and_login(
        client, app_sessions, slug="bloq-pg-rafaga", email="bloq-pg-rafaga@demo.com"
    )
    politica = await client.patch(
        "/stores/me",
        headers=auth_headers(admin),
        json={"deposit_policy": "La sena se descuenta del total."},
    )
    assert politica.status_code == 200, politica.text
    await _enable_payments(client, admin)
    await _configure_gateway(client, admin)
    service = await create_service(client, admin)
    staff = await create_staff(client, admin, service, email="staff-bloq-pg@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, admin, staff, target_date=dia)

    turnos: list[str] = []
    for i in range(TURNOS):
        alta = await client.post(
            "/appointments/",
            headers=auth_headers(admin),
            json={
                "service_id": service,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=10 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": f"Cliente Bloqueo {i}",
                "client_phone": f"+54911559{i:05d}",
                "idempotency_key": f"bloq-pg-alta-{i:04d}",
            },
        )
        assert alta.status_code == 201, alta.text
        turno = str(alta.json()["public_id"])
        link = await client.post(
            f"/payments/preferences/{turno}", headers=auth_headers(admin)
        )
        assert link.status_code == 200, link.text
        turnos.append(turno)

    antes = await _cobros(owner_engine)
    for i, turno in enumerate(turnos):
        cobro = antes[turno]
        assert (cobro["turno"], cobro["pago"]) == ("confirmed", "pending"), cobro
        mp.remotos[f"mp-bloq-{i}"] = {
            "id": f"mp-bloq-{i}",
            "status": "approved",
            # La del link de su preferencia (<turno>:<link_ref>), como MP.
            "external_reference": dict(mp.creadas)[cobro["preferencia"]],
            "preference_id": cobro["preferencia"],
            "transaction_amount": cobro["importe"],
            "currency_id": "ARS",
        }

    bloqueo = client.post(
        "/appointment-blocks/",
        headers=auth_headers(admin),
        json={
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=9, minute=0, second=0, microsecond=0
            ).isoformat(),
            "ends_at": dia.replace(
                hour=10 + TURNOS, minute=0, second=0, microsecond=0
            ).isoformat(),
            "reason": "Tramite",
            "cancel_affected": True,
        },
    )
    webhooks = [
        client.post(
            f"/payments/webhooks/mercadopago?store_id={store}",
            json={
                "id": f"evt-bloq-{i}",
                "type": "payment",
                "data": {"id": f"mp-bloq-{i}"},
            },
            headers=webhook_signature_headers(
                secret="secret-demo",
                data_id=f"mp-bloq-{i}",
                request_id=f"req-bloq-{i}",
                ts="0",
            ),
        )
        for i in range(TURNOS)
    ]
    respuestas: list[Response] = await asyncio.gather(bloqueo, *webhooks)

    assert all(r.status_code < 500 for r in respuestas), [
        (r.status_code, r.text[:200]) for r in respuestas if r.status_code >= 500
    ]
    assert respuestas[0].status_code == 201, respuestas[0].text
    for res in respuestas[1:]:
        assert res.status_code == 200, res.text
        cuerpo = res.json()
        assert cuerpo.get("data", cuerpo)["applied"] is True, cuerpo

    despues = await _cobros(owner_engine)
    eventos = await _eventos(owner_engine)
    for turno in turnos:
        final = despues[turno]
        assert final["pago"] == "approved", final
        vencimientos = [
            p
            for e, p in eventos
            if e == EVENT_PREFERENCE_EXPIRE and p.get("appointment_id") == turno
        ]
        avisos = [
            e
            for e, p in eventos
            if p.get("payment_id") == final["pago_id"]
            and e
            in {
                NotificationType.PAYMENT_APPROVED.value,
                NotificationType.PAYMENT_ON_RELEASED_APPOINTMENT.value,
            }
        ]
        assert len(avisos) == 1, (turno, avisos)
        if final["turno"] == "cancelled":
            assert [v["preference_id"] for v in vencimientos] == [
                final["preferencia"]
            ], vencimientos
            assert avisos == [NotificationType.PAYMENT_ON_RELEASED_APPOINTMENT.value]
        else:
            assert final["turno"] == "confirmed", final
            assert vencimientos == [], vencimientos
            assert avisos == [NotificationType.PAYMENT_APPROVED.value]


# ---------------------------------------------------------------------------
# Cancelacion del portal en rafaga (revision de perf/f4-pay, 2026-09-25, #2)
# ---------------------------------------------------------------------------

CANCELACIONES_PORTAL = 6


@pytest.mark.asyncio
async def test_rafaga_de_cancelaciones_del_portal_una_sola_gana(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N cancelaciones del cliente sobre el mismo turno a la vez (CLAUDE.md §4):
    1 x 200 y N-1 x 409 ``APPOINTMENT_ALREADY_CANCELLED``, cero 5xx, un solo
    ``appointment.slot_released`` y un solo aviso al dueno. Antes las N
    respondian 200 y cada una republicaba el cupo y el aviso."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    slug = "portal-cancela-rafaga"
    store, admin = await register_and_login(
        client, app_sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, admin)
    staff = await create_staff(client, admin, service, email=f"staff-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, admin, staff, target_date=dia)
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Rafaga Portal",
            "client_email": f"cliente-{slug}@example.com",
            "client_phone": TELEFONO_CLIENTE,
            "accepts_terms": True,
            "idempotency_key": f"{slug}-0001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    turno = str(reserva.json()["public_id"])
    pedido = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store,
            "phone": TELEFONO_CLIENTE,
            "channel": "whatsapp",
        },
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store,
            "phone": TELEFONO_CLIENTE,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text

    respuestas: list[Response] = await asyncio.gather(
        *(
            client.patch(
                f"/public/client/appointments/{turno}/cancel",
                json={"phone": TELEFONO_CLIENTE},
            )
            for _ in range(CANCELACIONES_PORTAL)
        )
    )

    codigos = sorted(r.status_code for r in respuestas)
    assert all(c < 500 for c in codigos), [r.text[:200] for r in respuestas]
    assert codigos == [200] + [409] * (CANCELACIONES_PORTAL - 1), codigos
    assert {r.json()["error_code"] for r in respuestas if r.status_code == 409} == {
        "APPOINTMENT_ALREADY_CANCELLED"
    }
    eventos = await _eventos(owner_engine)
    liberados = [
        e
        for e, p in eventos
        if e == "appointment.slot_released" and p.get("appointment_id") == turno
    ]
    avisos = [
        e
        for e, p in eventos
        if e == NotificationType.APPOINTMENT_CANCELLED_BY_CLIENT.value
        and p.get("appointment_id") == turno
    ]
    assert len(liberados) == 1, liberados
    assert len(avisos) == 1, avisos


# ---------------------------------------------------------------------------
# Confirmacion manual contra cancelar (revision de perf/f4-pay, 2026-09-25, #4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmacion_manual_contra_la_cancelacion_del_personal(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``POST /payments/{turno}/manual-confirm`` (admin) y la cancelacion del
    profesional sobre el mismo turno a la vez. Los dos lockean el turno
    primero y se serializan. Lo que se fija, sea cual sea el orden:
    - gano la cancelacion: la confirmacion es 409 ``APPOINTMENT_NOT_PAYABLE``
      y no hay cobro acreditado (no hay cobro o, si habia un link, vencido);
    - gano la confirmacion: cobro ``manual_confirmed`` y la cancelacion
      cancela el turno pagado como siempre (fuera de D2).
    Cero 5xx; la cancelacion siempre gana su 200; nunca un cobro acreditado
    que se registro DESPUES de cancelar (409 implica que no se acredito)."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    mp = _MercadoPago()
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    store, admin = await register_and_login(
        client, app_sessions, slug="manual-pg-rafaga", email="manual-pg@demo.com"
    )
    politica = await client.patch(
        "/stores/me",
        headers=auth_headers(admin),
        json={"deposit_policy": "La sena se descuenta del total."},
    )
    assert politica.status_code == 200, politica.text
    await _enable_payments(client, admin)
    await _configure_gateway(client, admin)
    service = await create_service(client, admin)
    staff = await create_staff(client, admin, service, email="staff-manual-pg@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, admin, staff, target_date=dia)
    profesional = await _profesional(client, admin)

    turnos: list[str] = []
    for i in range(CARRERAS):
        alta = await client.post(
            "/appointments/",
            headers=auth_headers(admin),
            json={
                "service_id": service,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=10 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": f"Cliente Manual {i}",
                "client_phone": f"+54911560{i:05d}",
                "idempotency_key": f"manual-pg-alta-{i:04d}",
            },
        )
        assert alta.status_code == 201, alta.text
        turnos.append(str(alta.json()["public_id"]))

    llamadas: list[Any] = []
    for turno in turnos:
        llamadas.append(
            client.post(
                f"/payments/{turno}/manual-confirm",
                headers=auth_headers(admin),
                json={"notes": "efectivo"},
            )
        )
        llamadas.append(
            client.patch(
                f"/appointments/{turno}/cancel", headers=auth_headers(profesional)
            )
        )
    respuestas: list[Response] = await asyncio.gather(*llamadas)

    assert all(r.status_code < 500 for r in respuestas), [
        (r.status_code, r.text[:200]) for r in respuestas if r.status_code >= 500
    ]
    estado = await _estado_de_turnos_y_cobros(owner_engine)
    async with owner_engine.connect() as conn:
        filas = await conn.execute(
            text(
                "select a.id, p.paid_at, a.cancelled_at from appointments a "
                "join payments p on p.appointment_id = a.id"
            )
        )
        momentos = {str(f[0]): (f[1], f[2]) for f in filas.all()}
    for i, turno in enumerate(turnos):
        manual, cancelacion = respuestas[2 * i], respuestas[2 * i + 1]
        turno_estado, cobros = estado[turno]
        assert cancelacion.status_code == 200, cancelacion.text
        assert turno_estado == "cancelled"
        acreditados = [c for c in cobros if c[0] == "manual_confirmed"]
        if manual.status_code == 409:
            assert manual.json()["error_code"] == "APPOINTMENT_NOT_PAYABLE"
            assert acreditados == [], (turno, cobros)
        else:
            assert manual.status_code == 200, manual.text
            assert len(acreditados) == 1, (turno, cobros)
            # Se registro ANTES de cancelar: bajo el lock del turno, la
            # confirmacion que llega despues de la cancelacion es 409.
            pagado, cancelado = momentos[turno]
            assert pagado is not None and cancelado is not None
            assert pagado <= cancelado, (turno, pagado, cancelado)


# ---------------------------------------------------------------------------
# Regenerar el link de un cobro vencido contra un webhook tardio de la
# preferencia vieja (revision de perf/f4-pay, 2026-09-25, #5 opcion b)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("estado_tardio", ["in_process", "approved"])
@pytest.mark.parametrize("con_cancelacion", [False, True])
async def test_regenerar_link_vencido_contra_webhook_tardio_de_la_preferencia_vieja(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    estado_tardio: str,
    con_cancelacion: bool,
) -> None:
    """Turnos confirmados cuyo link del panel vencio (cobro ``expired``). A la
    vez: el admin regenera el link, llega un webhook tardio (``in_process`` o
    ``approved``) de la preferencia VIEJA y, en una variante, el profesional
    cancela el turno.

    Todos toman el turno primero (regla 7). Lo que se fija en cualquier orden:
    cero 5xx; nunca un cobro vivo sobre un turno cancelado; nunca un cobro
    ``pending`` con la preferencia vieja (``in_process`` no reabre, el grafo
    general no tiene ``expired -> pending``); un ``approved`` de la vieja solo
    se registra si llego ANTES de la regeneracion (despues, la referencia del
    link no coincide y la integridad lo rechaza: ``applied`` false), y
    entonces con un solo aviso al dueno; y a lo sumo UN link vivo por turno
    (el del cobro): todo otro link creado tiene su vencimiento publicado.

    Revision de perf/f4-pay (hallazgo sobre 5d41644): el pago tardio viene
    como lo manda MP, SIN ``preference_id``; lo que distingue al link viejo es
    su ``external_reference`` (``<turno>:<link_ref>``).
    """
    monkeypatch.setattr(settings, "MERCADOPAGO_LINK_REF_ENABLED", True)
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    mp = _MercadoPago()
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    slug = f"regen-pg-{estado_tardio}-{int(con_cancelacion)}"
    store, admin = await register_and_login(
        client, app_sessions, slug=slug, email=f"{slug}@demo.com"
    )
    politica = await client.patch(
        "/stores/me",
        headers=auth_headers(admin),
        json={"deposit_policy": "La sena se descuenta del total."},
    )
    assert politica.status_code == 200, politica.text
    await _enable_payments(client, admin)
    await _configure_gateway(client, admin)
    service = await create_service(client, admin)
    staff = await create_staff(client, admin, service, email=f"staff-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, admin, staff, target_date=dia)
    profesional = await _profesional(client, admin)

    turnos: list[str] = []
    for i in range(TURNOS):
        alta = await client.post(
            "/appointments/",
            headers=auth_headers(admin),
            json={
                "service_id": service,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=10 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": f"Cliente Regen {i}",
                "client_phone": f"+54911561{i:05d}",
                "idempotency_key": f"{slug}-alta-{i:04d}",
            },
        )
        assert alta.status_code == 201, alta.text
        turno = str(alta.json()["public_id"])
        link = await client.post(
            f"/payments/preferences/{turno}", headers=auth_headers(admin)
        )
        assert link.status_code == 200, link.text
        turnos.append(turno)
    # MP vencio los links: los cobros quedan expired y los turnos, vivos.
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("update payments set status = 'expired', version = version + 1")
        )
    cobros_viejos = await _cobros(owner_engine)
    viejas = {t: c["preferencia"] for t, c in cobros_viejos.items()}
    referencias = dict(mp.creadas)
    async with owner_engine.connect() as conn:
        filas = await conn.execute(text("select id, store_id from payments"))
        tiendas: dict[str, str] = {str(f[0]): str(f[1]) for f in filas.all()}
    for i, turno in enumerate(turnos):
        cobro = cobros_viejos[turno]
        mp.remotos[f"mp-tarde-{i}"] = {
            "id": f"mp-tarde-{i}",
            "status": estado_tardio,
            # Como MP: sin preference_id; la referencia es la del link VIEJO.
            "external_reference": referencias[viejas[turno]],
            "metadata": {
                "appointment_id": turno,
                "payment_id": cobro["pago_id"],
                "store_id": tiendas[cobro["pago_id"]],
            },
            "transaction_amount": cobro["importe"],
            "currency_id": "ARS",
        }

    pedidos: list[tuple[str, str]] = []
    llamadas: list[Any] = []
    for i, turno in enumerate(turnos):
        pedidos.append((turno, "regenerar"))
        llamadas.append(
            client.post(f"/payments/preferences/{turno}", headers=auth_headers(admin))
        )
        pedidos.append((turno, "webhook"))
        llamadas.append(
            client.post(
                f"/payments/webhooks/mercadopago?store_id={store}",
                json={
                    "id": f"evt-tarde-{slug}-{i}",
                    "type": "payment",
                    "data": {"id": f"mp-tarde-{i}"},
                },
                headers=webhook_signature_headers(
                    secret="secret-demo",
                    data_id=f"mp-tarde-{i}",
                    request_id=f"req-tarde-{slug}-{i}",
                    ts="0",
                ),
            )
        )
        if con_cancelacion:
            pedidos.append((turno, "cancelar"))
            llamadas.append(
                client.patch(
                    f"/appointments/{turno}/cancel",
                    headers=auth_headers(profesional),
                )
            )
    respuestas: list[Response] = await asyncio.gather(*llamadas)

    assert all(r.status_code < 500 for r in respuestas), [
        (r.status_code, r.text[:200]) for r in respuestas if r.status_code >= 500
    ]
    finales = await _cobros(owner_engine)
    eventos = await _eventos(owner_engine)
    for turno in turnos:
        propias = {
            tipo: r
            for (t, tipo), r in zip(pedidos, respuestas, strict=True)
            if t == turno
        }
        final = finales[turno]
        regenerar, webhook = propias["regenerar"], propias["webhook"]
        assert regenerar.status_code in {200, 409}, regenerar.text
        if regenerar.status_code == 409:
            # Turno cancelado, o el pago tardio del link retirado se aplico
            # entre la fase 1 y la 2 (el cobro adopto ese link): la fase 2
            # choca con la version y vence el link que habia creado.
            assert regenerar.json()["error_code"] in {
                "APPOINTMENT_NOT_PAYABLE",
                "CONCURRENT_MODIFICATION",
            }, regenerar.text
        assert webhook.status_code == 200, webhook.text
        if con_cancelacion:
            assert propias["cancelar"].status_code == 200, propias["cancelar"].text
            assert final["turno"] == "cancelled", final
            assert final["pago"] not in {"pending", "rejected"}, final
        else:
            assert final["turno"] == "confirmed", final
        if final["pago"] == "pending":
            assert final["preferencia"] != viejas[turno], final
        aplicado = webhook.json().get("data", webhook.json())["applied"]
        avisos = [
            e
            for e, p in eventos
            if p.get("payment_id") == final["pago_id"]
            and e
            in {
                NotificationType.PAYMENT_APPROVED.value,
                NotificationType.PAYMENT_ON_RELEASED_APPOINTMENT.value,
            }
        ]
        if final["pago"] == "approved":
            assert estado_tardio == "approved" and aplicado, (final, aplicado)
            assert len(avisos) == 1, avisos
        else:
            assert avisos == [], avisos
        vencidas = {
            p["preference_id"] for e, p in eventos if e == EVENT_PREFERENCE_EXPIRE
        }
        vivos = {
            pref
            for pref, ref in mp.creadas
            if ref.split(":")[0] == turno and pref not in vencidas
        }
        assert vivos <= {final["preferencia"]}, (turno, vivos, final)


# ---------------------------------------------------------------------------
# Pago de un link retirado contra pago del link vigente (revision de
# 7abb9b4..e5579b6, 2026-09-25, #1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pago_del_link_retirado_contra_pago_del_link_vigente(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cobros regenerados (link L1 retirado, L2 vigente). A la vez llegan un
    ``approved`` tardio de L1 (webhook demorado) y un ``approved`` de L2.
    Los dos toman el turno primero (regla 7) y se serializan. Exactamente uno
    se aplica; el otro encuentra el cobro ya acreditado y va al camino de
    alerta como pago duplicado (una vez por pago de MP). Cero 5xx y un solo
    link vivo o pagado por cobro."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    mp = _MercadoPago()
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    slug = "retirado-pg-rafaga"
    store, admin = await register_and_login(
        client, app_sessions, slug=slug, email=f"{slug}@demo.com"
    )
    politica = await client.patch(
        "/stores/me",
        headers=auth_headers(admin),
        json={"deposit_policy": "La sena se descuenta del total."},
    )
    assert politica.status_code == 200, politica.text
    await _enable_payments(client, admin)
    await _configure_gateway(client, admin)
    service = await create_service(client, admin)
    staff = await create_staff(client, admin, service, email=f"staff-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, admin, staff, target_date=dia)

    turnos: list[str] = []
    for i in range(TURNOS):
        alta = await client.post(
            "/appointments/",
            headers=auth_headers(admin),
            json={
                "service_id": service,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=10 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": f"Cliente Retirado {i}",
                "client_phone": f"+54911562{i:05d}",
                "idempotency_key": f"{slug}-alta-{i:04d}",
            },
        )
        assert alta.status_code == 201, alta.text
        turno = str(alta.json()["public_id"])
        primero = await client.post(
            f"/payments/preferences/{turno}", headers=auth_headers(admin)
        )
        assert primero.status_code == 200, primero.text
        turnos.append(turno)
    viejas = {t: c["preferencia"] for t, c in (await _cobros(owner_engine)).items()}
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("update payments set status = 'expired', version = version + 1")
        )
    for turno in turnos:
        regenerado = await client.post(
            f"/payments/preferences/{turno}", headers=auth_headers(admin)
        )
        assert regenerado.status_code == 200, regenerado.text
    cobros = await _cobros(owner_engine)
    referencias = dict(mp.creadas)
    async with owner_engine.connect() as conn:
        filas = await conn.execute(text("select id, store_id from payments"))
        tiendas: dict[str, str] = {str(f[0]): str(f[1]) for f in filas.all()}

    def remoto(turno: str, preferencia: str, externo: str) -> dict[str, Any]:
        cobro = cobros[turno]
        return {
            "id": externo,
            "status": "approved",
            "external_reference": referencias[preferencia],
            "metadata": {
                "appointment_id": turno,
                "payment_id": cobro["pago_id"],
                "store_id": tiendas[cobro["pago_id"]],
            },
            "transaction_amount": cobro["importe"],
            "currency_id": "ARS",
        }

    llamadas: list[Any] = []
    for i, turno in enumerate(turnos):
        for tipo, preferencia in (
            ("viejo", viejas[turno]),
            ("nuevo", cobros[turno]["preferencia"]),
        ):
            externo = f"mp-{tipo}-{i}"
            mp.remotos[externo] = remoto(turno, preferencia, externo)
            llamadas.append(
                client.post(
                    f"/payments/webhooks/mercadopago?store_id={store}",
                    json={
                        "id": f"evt-{tipo}-{slug}-{i}",
                        "type": "payment",
                        "data": {"id": externo},
                    },
                    headers=webhook_signature_headers(
                        secret="secret-demo",
                        data_id=externo,
                        request_id=f"req-{tipo}-{slug}-{i}",
                        ts="0",
                    ),
                )
            )
    respuestas: list[Response] = await asyncio.gather(*llamadas)

    assert all(r.status_code < 500 for r in respuestas), [
        (r.status_code, r.text[:200]) for r in respuestas if r.status_code >= 500
    ]
    finales = await _cobros(owner_engine)
    eventos = await _eventos(owner_engine)
    vencidas = {p["preference_id"] for e, p in eventos if e == EVENT_PREFERENCE_EXPIRE}
    for i, turno in enumerate(turnos):
        viejo, nuevo = respuestas[2 * i], respuestas[2 * i + 1]
        aplicados = [r.json().get("data", r.json())["applied"] for r in (viejo, nuevo)]
        assert sorted(aplicados) == [False, True], (turno, aplicados)
        final = finales[turno]
        assert final["pago"] == "approved", final
        aprobados = [
            e
            for e, p in eventos
            if e == NotificationType.PAYMENT_APPROVED.value
            and p.get("payment_id") == final["pago_id"]
        ]
        duplicados = [
            p
            for e, p in eventos
            if e == "payment.received_on_replaced_link"
            and p.get("payment_id") == final["pago_id"]
        ]
        assert len(aprobados) == 1, aprobados
        assert len(duplicados) == 1 and duplicados[0]["duplicado"] is True, duplicados
        # Un solo link vivo o pagado: el pagado es el del cobro; el otro vencido.
        otra = (
            cobros[turno]["preferencia"]
            if final["preferencia"] == viejas[turno]
            else viejas[turno]
        )
        assert otra in vencidas, (turno, otra, vencidas)


# ---------------------------------------------------------------------------
# Reprogramar un turno con sena pendiente (decision de Mateo 2026-09-25:
# opcion A)
# ---------------------------------------------------------------------------

REPROGRAMACIONES = 4


@pytest.mark.asyncio
async def test_rafaga_de_reprogramaciones_de_un_pendiente_de_pago_no_toca_nada(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N reprogramaciones a la vez de cada turno en ``pending_payment``, a
    horarios distintos: todas 409 ``DEPOSIT_PENDING_RESCHEDULE_DENIED``, cero
    5xx, y la base igual que antes (turnos, cobros, links y outbox). El
    chequeo corre bajo el lock del turno, antes de toda mutacion."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    mp = _MercadoPago()
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    slug = "sena-reprograma-pg"
    store, admin = await register_and_login(
        client, app_sessions, slug=slug, email=f"{slug}@demo.com"
    )
    politica = await client.patch(
        "/stores/me",
        headers=auth_headers(admin),
        json={"deposit_policy": "La sena se descuenta del total."},
    )
    assert politica.status_code == 200, politica.text
    await _enable_payments(client, admin)
    await _configure_gateway(client, admin)
    service = await create_service(
        client,
        admin,
        deposit_mode="required",
        deposit_type="fixed",
        deposit_amount=2500,
    )
    staff = await create_staff(client, admin, service, email=f"staff-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, admin, staff, target_date=dia)
    turnos: list[str] = []
    for i in range(TURNOS):
        reserva = await client.post(
            "/public/appointments",
            json={
                "store_public_id": store,
                "service_id": service,
                "staff_id": staff,
                "starts_at": dia.replace(
                    hour=10 + i, minute=0, second=0, microsecond=0
                ).isoformat(),
                "client_name": f"Cliente Sena {i}",
                "client_phone": f"+54911558{i:05d}",
                "accepts_terms": True,
                "payment_method": "mercadopago",
                "idempotency_key": f"{slug}-reserva-{i:04d}",
            },
        )
        assert reserva.status_code == 201, reserva.text
        assert reserva.json()["status"] == "pending_payment"
        turnos.append(str(reserva.json()["public_id"]))
    antes = await _cobros(owner_engine)
    eventos_antes = await _eventos(owner_engine)

    llamadas = [
        client.patch(
            f"/appointments/{turno}/reschedule",
            headers=auth_headers(admin),
            json={
                "new_starts_at": dia.replace(
                    hour=14 + j % 3, minute=0, second=0, microsecond=0
                ).isoformat(),
                "idempotency_key": f"{slug}-mueve-{i}-{j}",
            },
        )
        for i, turno in enumerate(turnos)
        for j in range(REPROGRAMACIONES)
    ]
    respuestas: list[Response] = await asyncio.gather(*llamadas)

    assert all(r.status_code < 500 for r in respuestas), [
        (r.status_code, r.text[:200]) for r in respuestas if r.status_code >= 500
    ]
    assert {(r.status_code, r.json()["error_code"]) for r in respuestas} == {
        (409, "DEPOSIT_PENDING_RESCHEDULE_DENIED")
    }, [r.text[:200] for r in respuestas]
    assert await _cobros(owner_engine) == antes
    assert await _eventos(owner_engine) == eventos_antes
    async with owner_engine.connect() as conn:
        total = (
            await conn.execute(text("select count(*) from appointments"))
        ).scalar_one()
    assert total == TURNOS
