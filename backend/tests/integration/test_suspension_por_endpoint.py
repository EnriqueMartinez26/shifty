"""Tienda suspendida: que se bloquea y que sigue permitido, endpoint por endpoint.

2026-09-19 (audit B7-02 consolidado, con B4-03, B5-14 y B1-06). Sintoma: la
guarda `block_writes_when_suspended` era opt-in router por router y cuatro
routers con escritura quedaron afuera (users, ledger, notifications, reports):
una tienda que dejo de pagar seguia dando de alta usuarios y asentando
movimientos de cuenta corriente. Ademas el portal publico no tenia ninguna
guarda: la vitrina daba 404 pero `POST /public/appointments` y
`POST /public/waitlist` seguian aceptando reservas y altas.

Decision (OK global del usuario, sugerencia del brief): se permite el
housekeeping y se bloquea todo lo que genera una obligacion nueva.
- Panel: toda escritura se bloquea (402 SUBSCRIPTION_SUSPENDED) salvo las
  declaradas en `SUSPENSION_ALLOWED_WRITES`: marcar notificaciones leidas
  (B4-03), exportar lo propio (B5-14), dar de baja un usuario (criterio del
  coordinador, pendiente de confirmacion del usuario), las escrituras de panel
  de pagos (cobrar turnos ya tomados, operar la pasarela) y, desde
  D-20260930-12, cancelar y liberar turnos ya tomados (extinguen una
  obligacion y destraban la anonimizacion de clientes). Los movimientos de
  ledger, cargar y revertir, quedan bloqueados, y tambien crear, reprogramar y
  confirmar turnos.
- Portal publico (B1-06): se bloquea SOLO crear reservas y anotarse en la
  lista de espera (mismo 404 que la vitrina); cancelar y reprogramar turnos
  existentes siguen permitidos: no se castiga al cliente por la mora.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from main import app
import modules.billing.dependencies as guarda
import modules.payments.service as payments_service
from modules.appointments.model import Appointment
from modules.billing.dependencies import SAFE_METHODS, block_writes_when_suspended
from modules.billing.model import Plan, StoreSubscription
from modules.payments.model import OutboxMessage, Payment, PaymentStatus
from modules.payments.service import EVENT_PREFERENCE_EXPIRE
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

# Routers que NO pasan por la guarda del panel, cada uno con su motivo. Un
# router nuevo con escrituras que no este aca queda cubierto por defecto: el
# test estructural falla hasta que se lo guarde o se lo exima a proposito.
PREFIJOS_EXENTOS = {
    "/auth": "login, logout, sesiones y contrasena: el dueno tiene que poder entrar a pagar",
    "/superadmin": "es quien reactiva la tienda",
    "/ops": "operacion interna",
    "/public": "portal anonimo: sin usuario; la regla vive en los handlers (B1-06)",
}
PASSWORD = "Clave-Larga-2026!ok"
TELEFONO = "+5491155550977"


def _rutas_con_escritura() -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and set(route.methods) - SAFE_METHODS
    ]


def _exenta(path: str) -> bool:
    """Prefijo con limite de segmento: `/auth` no exime `/authorizations`."""
    return any(path == p or path.startswith(p + "/") for p in PREFIJOS_EXENTOS)


def test_el_prefijo_exento_respeta_el_limite_de_segmento() -> None:
    assert _exenta("/auth/login") and _exenta("/public")
    assert not _exenta("/authorizations")
    assert not _exenta("/publications/1")


def test_toda_escritura_del_panel_pasa_por_la_guarda() -> None:
    sin_guarda = []
    for route in _rutas_con_escritura():
        if _exenta(route.path):
            continue
        guardada = any(
            dep.call is block_writes_when_suspended
            for dep in route.dependant.dependencies
        )
        if not guardada:
            sin_guarda.append(f"{sorted(route.methods)} {route.path}")
    assert sin_guarda == [], sin_guarda


def test_las_escrituras_permitidas_existen_de_verdad() -> None:
    """Una excepcion que apunta a una ruta que no existe es una excepcion muerta."""
    rutas = {
        (method, route.path)
        for route in _rutas_con_escritura()
        for method in route.methods
    }
    # Por el modulo y no importado por nombre: si la tabla no existe, el test
    # falla por la asercion y no tumba la coleccion del archivo entero.
    permitidas = guarda.SUSPENSION_ALLOWED_WRITES
    assert permitidas <= rutas, permitidas - rutas


def test_de_turnos_solo_cancelar_y_liberar_sobreviven_a_la_suspension() -> None:
    """D-20260930-12: crear, reprogramar, confirmar y completar siguen bloqueados."""
    de_turnos = {
        clave
        for clave in guarda.SUSPENSION_ALLOWED_WRITES
        if clave[1].startswith("/appointments")
    }
    assert de_turnos == {
        ("PATCH", "/appointments/{public_id}/cancel"),
        ("PATCH", "/appointments/{public_id}/release"),
    }


async def _suspender(session: AsyncSession, store_public_id: str) -> None:
    store_id = (
        await session.execute(
            select(Store.id).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    plan = Plan(name=f"Plan {store_public_id}", price=15000, currency="ARS")
    session.add(plan)
    await session.flush()
    session.add(
        StoreSubscription(
            store_id=store_id,
            plan_id=plan.id,
            plan_name=plan.name,
            status="suspended",
            base_amount=plan.price,
            discount_amount=0,
            total_amount=plan.price,
            currency="ARS",
            current_period_start=datetime.now(timezone.utc) - timedelta(days=40),
            current_period_end=datetime.now(timezone.utc) - timedelta(days=10),
        )
    )
    await session.commit()


def _bloqueado(res: object) -> None:
    status = getattr(res, "status_code")
    assert status == 402, getattr(res, "text")
    assert getattr(res, "json")()["error_code"] == "SUBSCRIPTION_SUSPENDED"


def _no_bloqueado(res: object) -> None:
    """La guarda dejo pasar: el resultado lo decide el handler, no la suspension."""
    status = getattr(res, "status_code")
    assert status != 402, getattr(res, "text")
    if status >= 400:
        assert getattr(res, "json")().get("error_code") != "SUBSCRIPTION_SUSPENDED"


@pytest.mark.asyncio
async def test_panel_con_la_tienda_suspendida(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, token = await register_and_login(
        client, slug="susp-panel", email="susp-panel@example.com"
    )
    headers = auth_headers(token)
    empleado = await client.post(
        "/users/",
        headers=headers,
        json={
            "email": "empleado-susp@example.com",
            "password": PASSWORD,
            "first_name": "Emple",
            "last_name": "Ado",
        },
    )
    assert empleado.status_code == 201, empleado.text
    empleado_id = empleado.json()["public_id"]
    await _suspender(test_session, store)

    # users: alta y edicion bloqueadas; la baja sigue (cortar el acceso de un
    # ex empleado no puede esperar a que la tienda pague).
    _bloqueado(
        await client.post(
            "/users/",
            headers=headers,
            json={
                "email": "otro-susp@example.com",
                "password": PASSWORD,
                "first_name": "Otro",
                "last_name": "Mas",
            },
        )
    )
    _bloqueado(
        await client.patch(
            f"/users/{empleado_id}", headers=headers, json={"is_active": True}
        )
    )
    baja = await client.delete(f"/users/{empleado_id}", headers=headers)
    assert baja.status_code == 204, baja.text

    # ledger: cargar y revertir quedan bloqueados (revertir un pago le vuelve
    # a crear deuda al cliente; V-diff 2026-09-19).
    _bloqueado(
        await client.post(
            "/ledger/customers/01ABCDEFGHJKMNPQRSTVWXYZ00/movements",
            headers=headers,
            json={"movement_type": "charge", "amount": "100.00"},
        )
    )
    _bloqueado(
        await client.post(
            "/ledger/customers/01ABCDEFGHJKMNPQRSTVWXYZ00/movements/"
            "01ABCDEFGHJKMNPQRSTVWXYZ01/reverse",
            headers=headers,
        )
    )

    # payments: el router esta guardado pero sus escrituras de panel actuales
    # siguen (cobrar turnos ya tomados, operar la pasarela). El handler decide
    # el resultado; la guarda no corta.
    _no_bloqueado(
        await client.post(
            "/payments/01ABCDEFGHJKMNPQRSTVWXYZ00/manual-confirm", headers=headers
        )
    )
    _no_bloqueado(
        await client.delete("/payments/mercadopago/oauth/connection", headers=headers)
    )

    # notifications (B4-03): marcar leida no es escritura a estos fines.
    leer_todas = await client.post("/notifications/read-all", headers=headers)
    assert leer_todas.status_code == 200, leer_todas.text
    _no_bloqueado(
        await client.post(
            "/notifications/01ABCDEFGHJKMNPQRSTVWXYZ00/read", headers=headers
        )
    )

    # reports (B5-14): exportar lo propio sigue aunque sea POST.
    exportar = await client.post(
        "/reports/export", headers=headers, json={"format": "csv"}
    )
    assert exportar.status_code == 200, exportar.text

    # La lectura sigue en todos lados.
    assert (await client.get("/dashboard/summary", headers=headers)).status_code != 402
    assert (await client.get("/users/", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_portal_publico_con_la_tienda_suspendida(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    store, token = await register_and_login(
        client, slug="susp-portal", email="susp-portal@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    inicio = dia.replace(hour=13, minute=0, second=0, microsecond=0)
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": inicio.isoformat(),
            "client_name": "Cliente",
            # La autogestion exige una ficha con email ENTREGABLE verificado por
            # OTP (2026-09-20): sin email la ficha queda con el tecnico `.noreply`.
            "client_email": "cliente@example.com",
            "client_phone": TELEFONO,
            "accepts_terms": True,
            "idempotency_key": "susp-portal-0001",
        },
    )
    assert reserva.status_code == 201, reserva.text
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

    await _suspender(test_session, store)

    # Bloqueado: reservar y anotarse (mismo 404 que la vitrina, sin motivo).
    nueva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": (inicio + timedelta(hours=2)).isoformat(),
            "client_name": "Otra",
            "client_phone": "+5491155550978",
            "accepts_terms": True,
            "idempotency_key": "susp-portal-0002",
        },
    )
    assert nueva.status_code == 404, nueva.text
    assert nueva.json()["error_code"] == "STORE_NOT_FOUND"
    lista = await client.post(
        "/public/waitlist",
        json={
            "store_public_id": store,
            "service_id": service,
            "window_starts_at": inicio.isoformat(),
            "window_ends_at": (inicio + timedelta(hours=4)).isoformat(),
            "client_name": "Espera",
            "client_phone": "+5491155550979",
        },
    )
    assert lista.status_code == 404, lista.text
    assert lista.json()["error_code"] == "STORE_NOT_FOUND"

    # Permitido: el cliente reprograma y cancela su turno ya tomado.
    reprogramado = await client.patch(
        f"/public/client/appointments/{reserva.json()['public_id']}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": (inicio + timedelta(hours=1)).isoformat(),
            "idempotency_key": "susp-portal-reprog-01",
        },
    )
    assert reprogramado.status_code == 200, reprogramado.text
    # Se cancela el turno NUEVO: el original ya quedo cancelado al
    # reprogramar (cancelarlo otra vez es 409 APPOINTMENT_ALREADY_CANCELLED).
    cancelado = await client.patch(
        f"/public/client/appointments/{reprogramado.json()['public_id']}/cancel",
        json={"phone": TELEFONO},
    )
    assert cancelado.status_code == 200, cancelado.text


@pytest.mark.asyncio
async def test_tienda_suspendida_cancela_y_libera_turnos_ya_tomados(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-20260930-12: cancelar y liberar extinguen una obligacion y destraban la
    anonimizacion de clientes (se niega con turnos activos a futuro). Con la
    tienda suspendida el cobro vivo se vence igual (pago a `expired` y el
    `payment.preference.expire` al outbox, en la misma transaccion); crear,
    reprogramar y confirmar siguen en 402."""

    async def mp(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": "pref-susp-cancel",
            "init_point": "https://www.mercadopago.com/checkout?pref=susp-cancel",
        }

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    store, token = await register_and_login(
        client, slug="susp-cancel", email="susp-cancel@example.com"
    )
    headers = auth_headers(token)
    for url, cuerpo in (
        ("/stores/me/feature-flags", {"payments": True}),
        ("/payments/gateway-config", {"access_token": "TEST-SUSP-TOKEN"}),
    ):
        res = await client.put(url, headers=headers, json=cuerpo)
        assert res.status_code == 200, res.text
    service = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="fixed",
        deposit_amount=2500,
    )
    staff = await create_staff(
        client, token, service, email="pro-susp-cancel@example.com"
    )
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff, target_date=dia)

    def _inicio(hora: int) -> str:
        return dia.replace(hour=hora, minute=0, second=0, microsecond=0).isoformat()

    # Turno con sena pendiente (cobro vivo) y turno confirmado desde el panel,
    # ambos tomados ANTES de la suspension.
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": _inicio(12),
            "client_name": "Cliente Sena",
            "client_phone": "+5491155560001",
            "accepts_terms": True,
            "payment_method": "mercadopago",
            "idempotency_key": "susp-cancel-sena-01",
        },
    )
    assert reserva.status_code == 201, reserva.text
    assert reserva.json()["status"] == "pending_payment"
    pendiente = str(reserva.json()["public_id"])
    alta = await client.post(
        "/appointments/",
        headers=headers,
        json={
            "service_id": service,
            "staff_id": staff,
            "starts_at": _inicio(14),
            "client_name": "Cliente Panel",
            "client_phone": "+5491155560002",
            "idempotency_key": "susp-cancel-panel-01",
        },
    )
    assert alta.status_code == 201, alta.text
    confirmado = str(alta.json()["public_id"])
    await _suspender(test_session, store)

    # Sigue bloqueado: crear, reprogramar y confirmar generan obligaciones.
    _bloqueado(
        await client.post(
            "/appointments/",
            headers=headers,
            json={
                "service_id": service,
                "staff_id": staff,
                "starts_at": _inicio(16),
                "client_name": "Otro Cliente",
                "client_phone": "+5491155560003",
                "idempotency_key": "susp-cancel-panel-02",
            },
        )
    )
    _bloqueado(
        await client.patch(
            f"/appointments/{confirmado}/reschedule",
            headers=headers,
            json={"new_starts_at": _inicio(17)},
        )
    )
    _bloqueado(
        await client.patch(f"/appointments/{confirmado}/confirm", headers=headers)
    )

    # Permitido: liberar el pendiente de pago (queda `expired`) vence el cobro.
    liberado = await client.patch(f"/appointments/{pendiente}/release", headers=headers)
    assert liberado.status_code == 200, liberado.text
    test_session.expire_all()
    cobro = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == pendiente)
        )
    ).scalar_one()
    assert cobro.status == PaymentStatus.EXPIRED.value
    eventos = [
        e
        for e in (
            await test_session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == EVENT_PREFERENCE_EXPIRE
                )
            )
        ).scalars()
        if e.payload.get("appointment_id") == pendiente
    ]
    assert len(eventos) == 1, eventos

    # Permitido: cancelar el confirmado.
    cancelado = await client.patch(
        f"/appointments/{confirmado}/cancel", headers=headers
    )
    assert cancelado.status_code == 200, cancelado.text
    assert cancelado.json()["status"] == "cancelled"
    test_session.expire_all()
    estados = {
        fila.id: fila.status
        for fila in (
            await test_session.execute(
                select(Appointment).where(Appointment.id.in_([pendiente, confirmado]))
            )
        ).scalars()
    }
    assert estados == {pendiente: "expired", confirmado: "cancelled"}, estados
