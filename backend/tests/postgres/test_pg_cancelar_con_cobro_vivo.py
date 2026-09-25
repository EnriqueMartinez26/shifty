"""Rafaga: el personal cancela un turno con cobro vivo mientras llega el pago.

Decision del dueno (2026-09-25, D2): cancelar desde el panel un turno con
cobro vivo vence el cobro en la misma transaccion. Esto es lo que SQLite no
puede probar: N cancelaciones del profesional y el webhook de Mercado Pago
aprobando el MISMO turno a la vez, con una sesion por request.

Los dos caminos lockean en el mismo orden, turno -> pago (regla 7: el webhook
busca el cobro sin lock y despues lockea turno y pago, F1-18), asi que se
serializan sobre la fila del turno y no hay deadlock. Lo que el codigo
garantiza, sea cual sea el orden, y lo que se fija aca:

- cero 5xx; el webhook se aplica (200) y TODAS las cancelaciones responden
  200: cancelar un turno ya cancelado es un no-op de
  ``Appointment.apply_status_transition`` (mismo estado, sin error), como
  antes de D2. Lo que no se repite es el vencimiento: la segunda cancelacion
  encuentra el cobro ya vencido (o acreditado) y no publica otro.
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
            "external_reference": turno,
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
        # Cancelar lo ya cancelado es un no-op (mismo estado): todas 200.
        assert cancelaciones == [200] * CANCELACIONES, cancelaciones
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
