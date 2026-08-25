"""Caminos de error y borde de pagos y del API publico.

Los tests existentes recorren el camino feliz. Estos apuntan a las ramas de
rechazo: permisos, feature flags apagados, recursos ajenos y entradas que no
corresponden al estado actual.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


def _stub_mp(monkeypatch: pytest.MonkeyPatch) -> None:
    import modules.payments.service as payments_service

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": "pref-paths",
            "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=1",
        }

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


async def _tienda_con_cobros(
    client: AsyncClient, *, slug: str, email: str
) -> tuple[str, str]:
    store_public_id, token = await register_and_login(client, slug=slug, email=email)
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"payments": True},
    )
    assert flags.status_code == 200, flags.text
    gw = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={"access_token": "TEST-ACCESS-TOKEN-1234567890"},
    )
    assert gw.status_code == 200, gw.text
    return store_public_id, token


# ---------------------------------------------------------------------------
# Feature flag de cobros
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sin_el_flag_de_pagos_los_endpoints_estan_cerrados(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="pagos-apagados", email="pagos-off@test.com"
    )
    for metodo, ruta in [
        ("GET", "/payments/gateway-config"),
        ("GET", "/payments/reconciliation/summary"),
        ("GET", "/payments/outbox/stats"),
    ]:
        res = await client.request(metodo, ruta, headers=auth_headers(token))
        assert res.status_code == 403, f"{ruta} respondio {res.status_code}"


@pytest.mark.asyncio
async def test_la_conexion_oauth_se_puede_desconectar(client: AsyncClient) -> None:
    _, token = await _tienda_con_cobros(
        client, slug="pagos-desconecta", email="desconecta@test.com"
    )
    conectado = await client.get(
        "/payments/gateway-config", headers=auth_headers(token)
    )
    assert conectado.status_code == 200
    assert conectado.json()["configured"] is True

    baja = await client.delete(
        "/payments/mercadopago/oauth/connection", headers=auth_headers(token)
    )
    assert baja.status_code == 200, baja.text


@pytest.mark.asyncio
async def test_confirmar_a_mano_un_turno_inexistente_da_404(
    client: AsyncClient,
) -> None:
    _, token = await _tienda_con_cobros(
        client, slug="pagos-404", email="pagos404@test.com"
    )
    res = await client.post(
        "/payments/TURNOQUENOEXISTE/manual-confirm",
        headers=auth_headers(token),
        json={"amount": 100},
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_reembolsar_un_pago_inexistente_da_404(client: AsyncClient) -> None:
    _, token = await _tienda_con_cobros(
        client, slug="pagos-refund404", email="refund404@test.com"
    )
    res = await client.post(
        "/payments/PAGOQUENOEXISTE/refund",
        headers=auth_headers(token),
        json={"reason": "prueba"},
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_el_resumen_de_conciliacion_y_el_outbox_responden(
    client: AsyncClient,
) -> None:
    _, token = await _tienda_con_cobros(
        client, slug="pagos-resumen", email="resumen@test.com"
    )
    resumen = await client.get(
        "/payments/reconciliation/summary", headers=auth_headers(token)
    )
    assert resumen.status_code == 200, resumen.text
    assert resumen.json()["pending_payments"] == 0

    stats = await client.get("/payments/outbox/stats", headers=auth_headers(token))
    assert stats.status_code == 200, stats.text

    procesado = await client.post(
        "/payments/outbox/process", headers=auth_headers(token)
    )
    assert procesado.status_code == 200, procesado.text


# ---------------------------------------------------------------------------
# API publico
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_una_tienda_inexistente_da_404_en_el_booking(
    client: AsyncClient,
) -> None:
    res = await client.get("/public/stores/no-existe-esta-tienda")
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_los_servicios_publicos_se_listan_por_tienda(
    client: AsyncClient,
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="publico-servicios", email="pub-servicios@test.com"
    )
    await create_service(client, token)

    res = await client.get(
        "/public/services", params={"store_public_id": store_public_id}
    )
    assert res.status_code == 200, res.text
    assert len(res.json()) >= 1

    ajena = await client.get(
        "/public/services", params={"store_public_id": "TIENDAQUENOEXISTE"}
    )
    assert ajena.status_code == 404, ajena.text


@pytest.mark.asyncio
async def test_la_disponibilidad_publica_responde(client: AsyncClient) -> None:
    store_public_id, token = await register_and_login(
        client, slug="publico-dispo", email="pub-dispo@test.com"
    )
    service_public_id = await create_service(client, token)
    staff_public_id = await create_staff(client, token, service_public_id)
    dia = datetime.now(timezone.utc) + timedelta(days=3)
    await add_staff_schedule(client, token, staff_public_id, target_date=dia)

    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "date": dia.strftime("%Y-%m-%d"),
        },
    )
    assert res.status_code == 200, res.text
    assert isinstance(res.json(), list)


@pytest.mark.asyncio
async def test_reservar_un_servicio_de_otra_tienda_se_rechaza(
    client: AsyncClient,
) -> None:
    """Cruzar ids entre tiendas no puede crear un turno."""
    store_a, token_a = await register_and_login(
        client, slug="cruce-a", email="cruce-a@test.com"
    )
    servicio_a = await create_service(client, token_a)
    staff_a = await create_staff(client, token_a, servicio_a)
    dia = datetime.now(timezone.utc) + timedelta(days=3)
    await add_staff_schedule(client, token_a, staff_a, target_date=dia)

    store_b, _token_b = await register_and_login(
        client, slug="cruce-b", email="cruce-b@test.com"
    )

    res = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_b,
            "service_id": servicio_a,
            "staff_id": staff_a,
            "starts_at": dia.replace(
                hour=10, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Cruzado",
            "client_phone": "+5491155511100",
            "accepts_terms": True,
            "idempotency_key": "cruce-tiendas-0001",
        },
    )
    assert res.status_code >= 400, "se reservo un servicio de otra tienda"


@pytest.mark.asyncio
async def test_el_estado_de_un_pago_ajeno_no_se_puede_consultar(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_mp(monkeypatch)
    store_a, token_a = await _tienda_con_cobros(
        client, slug="pago-privado-a", email="pago-priv-a@test.com"
    )
    servicio = await create_service(
        client,
        token_a,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token_a, servicio)
    dia = datetime.now(timezone.utc) + timedelta(days=3)
    await add_staff_schedule(client, token_a, staff, target_date=dia)

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_a,
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=12, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Privado",
            "client_phone": "+5491155522200",
            "payment_method": "mercadopago",
            "accepts_terms": True,
            "idempotency_key": "pago-privado-0001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    payment_id = cast(str, reserva.json()["payment_public_id"])

    store_b, _ = await register_and_login(
        client, slug="pago-privado-b", email="pago-priv-b@test.com"
    )
    ajeno = await client.get(
        f"/public/payments/{payment_id}/status",
        params={"store_public_id": store_b},
    )
    assert ajeno.status_code == 404, "una tienda vio el pago de otra"


@pytest.mark.asyncio
async def test_una_promocion_inexistente_no_se_puede_previsualizar(
    client: AsyncClient,
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="promo-inexistente", email="promo-inex@test.com"
    )
    service_public_id = await create_service(client, token)

    res = await client.get(
        "/public/promotions/preview",
        params={
            "store_public_id": store_public_id,
            "service_id": service_public_id,
            "code": "NOEXISTE",
        },
    )
    assert res.status_code >= 400, res.text


@pytest.mark.asyncio
async def test_el_otp_se_pide_y_se_valida(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store_public_id, _token = await register_and_login(
        client, slug="otp-flujo", email="otp-flujo@test.com"
    )

    pedido = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store_public_id,
            "phone": "+5491155533300",
            "channel": "whatsapp",
        },
    )
    assert pedido.status_code == 200, pedido.text
    codigo = pedido.json().get("debug_code")
    assert codigo, "el entorno de test deberia exponer el codigo"

    malo = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store_public_id,
            "phone": "+5491155533300",
            "code": "000000" if codigo != "000000" else "111111",
        },
    )
    assert malo.status_code >= 400, "acepto un codigo incorrecto"

    bueno = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store_public_id,
            "phone": "+5491155533300",
            "code": codigo,
        },
    )
    assert bueno.status_code == 200, bueno.text
