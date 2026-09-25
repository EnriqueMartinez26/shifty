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
  coordinador, pendiente de confirmacion del usuario) y las escrituras de panel
  de pagos (cobrar turnos ya tomados, operar la pasarela). Los movimientos de
  ledger, cargar y revertir, quedan bloqueados.
- Portal publico (B1-06): se bloquea SOLO crear reservas y anotarse en la
  lista de espera (mismo 404 que la vitrina); cancelar y reprogramar turnos
  existentes siguen permitidos: no se castiga al cliente por la mora.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from main import app
import modules.billing.dependencies as guarda
from modules.billing.dependencies import SAFE_METHODS, block_writes_when_suspended
from modules.billing.model import Plan, StoreSubscription
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
