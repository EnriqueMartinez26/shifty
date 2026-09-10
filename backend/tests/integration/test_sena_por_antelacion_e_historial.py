"""Sena por antelacion e historial (Fase 5, 2026-09-10).

La regla se evalua una vez por reserva y el resultado viaja hasta el pago
(snapshot) y la respuesta; el preview publico usa la misma regla; un
reintento con la misma clave devuelve el mismo monto; la antelacion minima
pasa a ser editable.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from modules.payments.model import Payment
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon

REGLAS = {
    "deposit_far_notice_days": 7,
    "deposit_far_notice_extra_percent": 20,
    "deposit_new_client_extra_percent": 10,
    "deposit_absent_client_extra_percent": 30,
}


async def _mp_fake(
    access_token: str,
    *,
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "pref-sena",
        "init_point": "https://www.mercadopago.com/checkout/v1/redirect?pref=sena",
    }


async def _tienda_con_sena(client: AsyncClient, slug: str) -> tuple[str, str, str, str]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags", headers=auth_headers(token), json={"payments": True}
    )
    assert flags.status_code == 200, flags.text
    gateway = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={
            "access_token": "TEST-ACCESS-TOKEN-1234567890",
            "public_key": "TEST-PUBLIC-KEY",
            "webhook_secret": "secret-demo",
        },
    )
    assert gateway.status_code == 200, gateway.text
    reglas = await client.patch("/stores/me", headers=auth_headers(token), json=REGLAS)
    assert reglas.status_code == 200, reglas.text
    assert reglas.json()["deposit_far_notice_extra_percent"] == 20
    service = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    for dias in (2, 10):
        await add_staff_schedule(
            client,
            token,
            staff,
            target_date=datetime.now(timezone.utc) + timedelta(days=dias),
        )
    return store, token, service, staff


def _slot(dias: int) -> datetime:
    return (datetime.now(timezone.utc) + timedelta(days=dias)).replace(
        hour=13, minute=0, second=0, microsecond=0
    )


async def _preview(
    client: AsyncClient, store: str, service: str, dias: int, phone: str
) -> dict:
    res = await client.get(
        "/public/deposit/preview",
        params={
            "store_public_id": store,
            "service_id": service,
            "starts_at": _slot(dias).isoformat(),
            "client_phone": phone,
        },
    )
    assert res.status_code == 200, res.text
    return dict(res.json())


@pytest.mark.asyncio
async def test_cliente_nuevo_con_mucha_antelacion_paga_los_recargos_y_queda_el_snapshot(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", _mp_fake)
    store, _token, service, staff = await _tienda_con_sena(client, "sena-nuevo")

    preview = await _preview(client, store, service, 10, "+5491155550301")
    # base 30% + 20 (antelacion >= 7 dias) + 10 (cliente nuevo) = 60% de 10000
    assert preview["amount"] == 6000.0
    assert preview["base_amount"] == 3000.0
    assert preview["reasons"] == ["base", "far_notice", "new_client"]
    assert preview["online_payment_mandatory"] is False

    cuerpo = {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": _slot(10).isoformat(),
        "client_name": "Nuevo Lejano",
        "client_phone": "+5491155550301",
        "payment_method": "auto",
        "idempotency_key": "sena-nuevo-000001",
    }
    reserva = await client.post("/public/appointments", json=cuerpo)
    assert reserva.status_code == 201, reserva.text
    assert reserva.json()["payment_required"] is True
    assert reserva.json()["payment_amount"] == 6000.0

    # Reintento con la misma clave: mismo monto, mismo turno.
    repetida = await client.post("/public/appointments", json=cuerpo)
    assert repetida.status_code == 201, repetida.text
    assert repetida.json()["public_id"] == reserva.json()["public_id"]
    assert repetida.json()["payment_amount"] == 6000.0

    pago = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == reserva.json()["public_id"])
        )
    ).scalar_one()
    assert str(pago.amount) == "6000.00"
    assert pago.deposit_rule == {
        "amount": "6000.00",
        "base_amount": "3000.00",
        "extra_percent": 30,
        "reasons": ["base", "far_notice", "new_client"],
    }


@pytest.mark.asyncio
async def test_el_historial_del_cliente_cambia_la_sena(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff = await _tienda_con_sena(client, "sena-historial")
    telefono = "+5491155550302"

    # Sin historial y con poca antelacion: base + cliente nuevo.
    assert _reasons(await _preview(client, store, service, 2, telefono)) == [
        "base",
        "new_client",
    ]

    # Un turno completado lo vuelve cliente habitual: solo la base.
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": _slot(2).isoformat(),
            "client_name": "Cliente Historial",
            "client_phone": telefono,
            "payment_method": "manual",
            "idempotency_key": "sena-historial-000001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    pid = reserva.json()["public_id"]
    for accion in ("confirm", "complete"):
        res = await client.patch(
            f"/appointments/{pid}/{accion}", headers=auth_headers(token)
        )
        assert res.status_code == 200, res.text
    habitual = await _preview(client, store, service, 2, telefono)
    assert _reasons(habitual) == ["base"]
    assert habitual["amount"] == 3000.0

    # Una ausencia suma el recargo por faltas.
    otra = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": (_slot(2) + timedelta(hours=1)).isoformat(),
            "client_name": "Cliente Historial",
            "client_phone": telefono,
            "payment_method": "manual",
            "idempotency_key": "sena-historial-000002",
        },
    )
    assert otra.status_code == 201, otra.text
    pid2 = otra.json()["public_id"]
    for accion in ("confirm", "absent"):
        res = await client.patch(
            f"/appointments/{pid2}/{accion}", headers=auth_headers(token)
        )
        assert res.status_code == 200, res.text
    faltador = await _preview(client, store, service, 2, telefono)
    assert _reasons(faltador) == ["base", "absences"]
    assert faltador["amount"] == 6000.0


def _reasons(preview: dict) -> list[str]:
    return list(preview["reasons"])


@pytest.mark.asyncio
async def test_la_antelacion_minima_es_editable_y_se_aplica_al_alta(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff = await _tienda_con_sena(client, "sena-antelacion")

    cambio = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"min_booking_notice_hours": 72},
    )
    assert cambio.status_code == 200, cambio.text
    assert cambio.json()["min_booking_notice_hours"] == 72
    ajustes = await client.get("/stores/me", headers=auth_headers(token))
    assert ajustes.json()["min_booking_notice_hours"] == 72

    tarde = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": _slot(2).isoformat(),
            "client_name": "Apurado",
            "client_phone": "+5491155550303",
            "payment_method": "manual",
            "idempotency_key": "sena-antelacion-000001",
        },
    )
    assert tarde.status_code == 400, tarde.text
    assert tarde.json()["error_code"] == "BOOKING_NOTICE_REQUIRED"

    fuera_de_rango = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"deposit_far_notice_extra_percent": 150},
    )
    assert fuera_de_rango.status_code == 422, fuera_de_rango.text
