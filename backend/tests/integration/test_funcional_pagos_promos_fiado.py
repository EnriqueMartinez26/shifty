"""Correccion funcional: ingresos por cobro real, buffer, borrar promo, revertir fiado.

Cubre los arreglos de completitud pedidos sobre la revision funcional:

- El ingreso es la plata efectivamente cobrada (pago acreditado), no el turno
  agendado ni el precio de lista actual.
- El precio se congela al reservar (snapshot), asi el cobro y el reporte usan
  el valor de ese momento aunque despues cambie la lista.
- buffer_minutes se respeta al reservar (hueco obligatorio entre turnos).
- Las promociones se pueden dar de baja (borrado logico) y dejan de canjearse.
- Un movimiento de fiado mal cargado se puede revertir una unica vez.
"""

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


def _at(base: datetime, hour: int, minute: int = 0) -> str:
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


async def _book_admin(
    client: AsyncClient,
    token: str,
    *,
    service_id: str,
    staff_id: str,
    starts_at: str,
    clave: str,
) -> "tuple[int, dict]":
    res = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": service_id,
            "staff_id": staff_id,
            "starts_at": starts_at,
            "idempotency_key": clave,
        },
    )
    body = res.json() if res.content else {}
    return res.status_code, body


# ---------------------------------------------------------------------------
# Ingreso = plata cobrada, no turno agendado
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turno_sin_pago_no_cuenta_como_ingreso(client: AsyncClient) -> None:
    store, token = await register_and_login(
        client, slug="rev-sinpago", email="rev-sinpago@test.com"
    )
    servicio = await create_service(client, token)  # price 10000, sin sena
    staff = await create_staff(client, token, servicio)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)

    code, body = await _book_admin(
        client,
        token,
        service_id=servicio,
        staff_id=staff,
        starts_at=_at(dia, 11),
        clave="rev-sinpago-1",
    )
    assert code == 201, body

    fecha = dia.date().isoformat()
    summary = await client.get(
        f"/reports/summary?from_date={fecha}&to_date={fecha}",
        headers=auth_headers(token),
    )
    assert summary.status_code == 200, summary.text
    # Hay un turno, pero nadie pago: es una reserva, no un ingreso.
    assert summary.json()["stats"]["total_appointments"] == 1
    assert summary.json()["stats"]["total_revenue"] == 0.0


@pytest.mark.asyncio
async def test_dashboard_cuenta_pendientes_y_proximos(client: AsyncClient) -> None:
    """Regresion del bug de casing: el dashboard filtraba estados en MAYUSCULAS
    y el dominio los guarda en minusculas, asi que pendientes y proximos daban
    siempre 0/vacio. Estos dos no dependen de la ventana semanal."""
    store, token = await register_and_login(
        client, slug="dash-casing", email="dash-casing@test.com"
    )
    servicio = await create_service(client, token)
    staff = await create_staff(client, token, servicio)
    dia = datetime.now(timezone.utc) + timedelta(days=3)
    await add_staff_schedule(client, token, staff, target_date=dia)

    code, _ = await _book_admin(
        client,
        token,
        service_id=servicio,
        staff_id=staff,
        starts_at=_at(dia, 10),
        clave="dash-pendiente-1",
    )
    assert code == 201

    summary = await client.get("/dashboard/summary", headers=auth_headers(token))
    assert summary.status_code == 200, summary.text
    stats = summary.json()["stats"]
    # Antes del fix ambos eran siempre 0/vacio por el casing.
    assert stats["pending_confirmations"] >= 1
    assert len(summary.json()["upcoming_appointments"]) >= 1


@pytest.mark.asyncio
async def test_cobro_manual_convierte_reserva_en_ingreso(client: AsyncClient) -> None:
    store, token = await register_and_login(
        client, slug="rev-cobro", email="rev-cobro@test.com"
    )
    await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    servicio = await create_service(client, token)  # price 10000
    staff = await create_staff(client, token, servicio)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)

    code, booking = await _book_admin(
        client,
        token,
        service_id=servicio,
        staff_id=staff,
        starts_at=_at(dia, 12),
        clave="rev-cobro-1",
    )
    assert code == 201, booking

    # El dueno confirma que le pagaron (efectivo/WhatsApp), sin indicar monto:
    # debe tomar el precio congelado del turno (10000), no la sena ni 0.
    manual = await client.post(
        f"/payments/{booking['public_id']}/manual-confirm",
        headers=auth_headers(token),
        json={},
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["status"] == "manual_confirmed"
    assert manual.json()["amount"] == "10000.00"

    fecha = dia.date().isoformat()
    summary = await client.get(
        f"/reports/summary?from_date={fecha}&to_date={fecha}",
        headers=auth_headers(token),
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["stats"]["total_revenue"] == 10000.0


@pytest.mark.asyncio
async def test_resumen_agrega_ingresos_conteos_y_servicios(client: AsyncClient) -> None:
    """Caracteriza la agregacion de get_summary: fija ingresos (solo cobrados),
    conteos por estado y el bucket de servicio. Blinda el refactor del metodo."""
    store, token = await register_and_login(
        client, slug="rev-agg", email="rev-agg@test.com"
    )
    await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    servicio = await create_service(client, token)  # price 10000
    staff = await create_staff(client, token, servicio)
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff, target_date=dia)

    ids = []
    for i, hora in enumerate((9, 10, 11)):
        code, body = await _book_admin(
            client,
            token,
            service_id=servicio,
            staff_id=staff,
            starts_at=_at(dia, hora),
            clave=f"rev-agg-slot-{i}",
        )
        assert code == 201, body
        ids.append(body["public_id"])

    # Se cobran 2 de 3: el ingreso debe ser 20000, no 30000 (el tercero es reserva).
    for public_id in ids[:2]:
        manual = await client.post(
            f"/payments/{public_id}/manual-confirm",
            headers=auth_headers(token),
            json={},
        )
        assert manual.status_code == 200, manual.text

    fecha = dia.date().isoformat()
    summary = await client.get(
        f"/reports/summary?from_date={fecha}&to_date={fecha}",
        headers=auth_headers(token),
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["stats"]["total_appointments"] == 3
    assert body["stats"]["total_revenue"] == 20000.0
    assert body["stats"]["confirmed_appointments"] == 2
    assert body["stats"]["pending_appointments"] == 1
    top = body["top_services"][0]
    assert top["service_id"] == servicio
    assert top["appointments"] == 3
    assert top["revenue"] == 20000.0


@pytest.mark.asyncio
async def test_el_cobro_usa_el_precio_congelado_no_el_de_lista(
    client: AsyncClient,
) -> None:
    store, token = await register_and_login(
        client, slug="rev-snapshot", email="rev-snapshot@test.com"
    )
    await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    servicio = await create_service(client, token)  # price 10000
    staff = await create_staff(client, token, servicio)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)

    code, booking = await _book_admin(
        client,
        token,
        service_id=servicio,
        staff_id=staff,
        starts_at=_at(dia, 13),
        clave="rev-snapshot-1",
    )
    assert code == 201, booking

    # Sube el precio de lista DESPUES de reservar.
    subir = await client.patch(
        f"/services/{servicio}",
        headers=auth_headers(token),
        json={"price": 20000},
    )
    assert subir.status_code == 200, subir.text

    # El cobro sigue siendo por lo que valia al reservar: 10000.
    manual = await client.post(
        f"/payments/{booking['public_id']}/manual-confirm",
        headers=auth_headers(token),
        json={},
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["amount"] == "10000.00"


# ---------------------------------------------------------------------------
# buffer_minutes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_buffer_minutes_impide_reservar_demasiado_cerca(
    client: AsyncClient,
) -> None:
    store, token = await register_and_login(
        client, slug="buffer-1", email="buffer-1@test.com"
    )
    ajuste = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"buffer_minutes": 30},
    )
    assert ajuste.status_code == 200, ajuste.text
    assert ajuste.json()["buffer_minutes"] == 30

    servicio = await create_service(client, token)  # 30 min
    staff = await create_staff(client, token, servicio)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)

    # Turno base 11:00-11:30.
    code, _ = await _book_admin(
        client,
        token,
        service_id=servicio,
        staff_id=staff,
        starts_at=_at(dia, 11),
        clave="buffer-base",
    )
    assert code == 201

    # 11:45 deja apenas 15 min de hueco (< 30): se rechaza.
    code_cerca, _ = await _book_admin(
        client,
        token,
        service_id=servicio,
        staff_id=staff,
        starts_at=_at(dia, 11, 45),
        clave="buffer-cerca",
    )
    assert code_cerca == 409, code_cerca

    # 12:00 deja exactamente 30 min: se permite.
    code_ok, body_ok = await _book_admin(
        client,
        token,
        service_id=servicio,
        staff_id=staff,
        starts_at=_at(dia, 12),
        clave="buffer-okok",
    )
    assert code_ok == 201, (code_ok, body_ok)


# ---------------------------------------------------------------------------
# Borrado de promociones
# ---------------------------------------------------------------------------


async def _crear_promo(client: AsyncClient, token: str, code: str) -> str:
    res = await client.post(
        "/promotions/",
        headers=auth_headers(token),
        json={
            "code": code,
            "title": "Descuento",
            "promotion_type": "percent",
            "value": 10,
        },
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


@pytest.mark.asyncio
async def test_baja_de_promocion_la_saca_de_uso(client: AsyncClient) -> None:
    store, token = await register_and_login(
        client, slug="promo-del", email="promo-del@test.com"
    )
    servicio = await create_service(client, token)
    promo = await _crear_promo(client, token, "PROMO10")

    borrar = await client.delete(f"/promotions/{promo}", headers=auth_headers(token))
    assert borrar.status_code == 204, borrar.text

    # Ya no figura entre las activas.
    activas = await client.get(
        "/promotions/?include_inactive=false", headers=auth_headers(token)
    )
    assert activas.status_code == 200
    assert all(p["public_id"] != promo for p in activas.json())

    # Y no se puede canjear (ValidationException -> 422).
    preview = await client.get(
        f"/promotions/preview?service_id={servicio}&code=PROMO10",
        headers=auth_headers(token),
    )
    assert preview.status_code == 422, preview.text
    assert "no esta activa" in preview.json()["message"]


# ---------------------------------------------------------------------------
# Reversa de movimientos de fiado
# ---------------------------------------------------------------------------


async def _client_id_de_una_reserva(client: AsyncClient, token: str, store: str) -> str:
    servicio = await create_service(client, token)
    staff = await create_staff(client, token, servicio)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    booking = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": _at(dia, 15),
            "client_name": "Cliente Fiado",
            "client_phone": "+5491100011122",
            "idempotency_key": "fiado-cliente-1",
        },
    )
    assert booking.status_code == 201, booking.text
    search = await client.get(
        "/appointments/search?page=1&page_size=10", headers=auth_headers(token)
    )
    return cast(
        str,
        next(
            item
            for item in search.json()["results"]
            if item["public_id"] == booking.json()["public_id"]
        )["client_id"],
    )


@pytest.mark.asyncio
async def test_reversa_de_movimiento_devuelve_el_saldo(client: AsyncClient) -> None:
    store, token = await register_and_login(
        client, slug="fiado-rev", email="fiado-rev@test.com"
    )
    await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"ledger": True},
    )
    client_id = await _client_id_de_una_reserva(client, token, store)

    cargo = await client.post(
        f"/ledger/customers/{client_id}/movements",
        headers=auth_headers(token),
        json={"movement_type": "charge", "amount": "100.00", "notes": "mal cargado"},
    )
    assert cargo.status_code == 200, cargo.text
    assert cargo.json()["balance_after"] == "100.00"
    movimiento_id = cargo.json()["public_id"]

    reversa = await client.post(
        f"/ledger/customers/{client_id}/movements/{movimiento_id}/reverse",
        headers=auth_headers(token),
    )
    assert reversa.status_code == 200, reversa.text
    # El ajuste compensa el cargo: saldo de nuevo en cero.
    assert reversa.json()["balance_after"] == "0.00"
    assert reversa.json()["movement_type"] == "adjustment"

    # No se puede revertir dos veces el mismo movimiento (Validation -> 422).
    otra = await client.post(
        f"/ledger/customers/{client_id}/movements/{movimiento_id}/reverse",
        headers=auth_headers(token),
    )
    assert otra.status_code == 422, otra.text
    assert "ya fue revertido" in otra.json()["message"]

    # El saldo del cliente quedo saldado.
    cuenta = await client.get(
        f"/ledger/customers/{client_id}", headers=auth_headers(token)
    )
    assert cuenta.status_code == 200, cuenta.text
    assert cuenta.json()["balance"] == "0.00"
