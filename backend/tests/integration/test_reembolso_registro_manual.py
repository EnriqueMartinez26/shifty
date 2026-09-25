"""``POST /payments/{id}/refund`` es un REGISTRO de un reembolso hecho a mano.

2026-09-18, hallazgo B2-05 (Alta): el endpoint marcaba el cobro ``refunded``
sin pedirle nada a Mercado Pago. Con ``manual`` ausente o ``false`` el
sistema informaba "reembolsado", el turno podia cancelarse y la conciliacion
lo contaba en ``refunded_payments``, pero la plata seguia en la cuenta de MP
de la tienda: ningun reporte mostraba la diferencia.

Decision de Mateo (OK global, 2026-09-18): por ahora el endpoint solo
REGISTRA un reembolso hecho fuera de Shifty, con ``manual: true``. Un
reembolso automatico real es irreversible y necesita compensacion probada:
no es esta pasada. La ruta y el nombre no cambian (contrato del front).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.service as payments_service
from main import app
from modules.payments.model import Payment, PaymentStatus
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
)


def _mercadopago_prohibido(
    monkeypatch: pytest.MonkeyPatch, llamadas: list[str]
) -> None:
    async def prohibido(access_token: str, *, method: str, path: str, **_: Any) -> Any:
        llamadas.append(f"{method} {path}")
        raise AssertionError(f"el reembolso no debe llamar a Mercado Pago: {path}")

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", prohibido)


async def _cobro_acreditado(client: AsyncClient, slug: str) -> tuple[str, str]:
    """(token, payment_public_id) de un cobro confirmado a mano."""
    _store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    servicio = await create_service(client, token)
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reserva = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=11, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": f"{slug}-turno",
        },
    )
    assert reserva.status_code == 201, reserva.text
    confirmado = await client.post(
        f"/payments/{reserva.json()['public_id']}/manual-confirm",
        headers=auth_headers(token),
        json={},
    )
    assert confirmado.status_code == 200, confirmado.text
    return token, cast(str, confirmado.json()["public_id"])


async def _estado(session: AsyncSession, payment_id: str) -> str:
    session.expire_all()
    pago = (
        await session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one()
    return pago.status


@pytest.mark.asyncio
@pytest.mark.parametrize("cuerpo", [{"reason": "sin flag"}, {"manual": False}])
async def test_sin_manual_true_no_se_marca_reembolsado(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    cuerpo: dict[str, Any],
) -> None:
    llamadas: list[str] = []
    _mercadopago_prohibido(monkeypatch, llamadas)
    token, cobro = await _cobro_acreditado(client, "refund-sin-manual")

    res = await client.post(
        f"/payments/{cobro}/refund", headers=auth_headers(token), json=cuerpo
    )

    assert res.status_code == 422, res.text
    assert "fuera de Shifty" in res.json()["message"]
    assert await _estado(test_session, cobro) == PaymentStatus.MANUAL_CONFIRMED.value
    assert llamadas == []


@pytest.mark.asyncio
async def test_con_manual_true_registra_sin_llamar_a_mp_y_una_sola_vez(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llamadas: list[str] = []
    _mercadopago_prohibido(monkeypatch, llamadas)
    token, cobro = await _cobro_acreditado(client, "refund-manual")

    primero = await client.post(
        f"/payments/{cobro}/refund",
        headers=auth_headers(token),
        json={"manual": True, "reason": "devuelto en efectivo"},
    )
    assert primero.status_code == 200, primero.text
    assert primero.json()["status"] == PaymentStatus.REFUNDED.value
    assert llamadas == []

    # refunded es terminal: un cobro ya reembolsado no se reembolsa dos veces.
    segundo = await client.post(
        f"/payments/{cobro}/refund",
        headers=auth_headers(token),
        json={"manual": True},
    )
    assert segundo.status_code == 422, segundo.text
    assert await _estado(test_session, cobro) == PaymentStatus.REFUNDED.value


@pytest.mark.asyncio
async def test_otra_tienda_no_puede_registrar_el_reembolso(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _token_a, cobro_de_a = await _cobro_acreditado(client, "refund-tienda-a")
    _store_b, token_b = await register_and_login(
        client, slug="refund-tienda-b", email="refund-tienda-b@t.com"
    )
    await _enable_payments(client, token_b)

    ajeno = await client.post(
        f"/payments/{cobro_de_a}/refund",
        headers=auth_headers(token_b),
        json={"manual": True},
    )
    assert ajeno.status_code == 404, ajeno.text
    assert (
        await _estado(test_session, cobro_de_a) == PaymentStatus.MANUAL_CONFIRMED.value
    )


def test_el_openapi_documenta_que_es_un_registro() -> None:
    operacion = app.openapi()["paths"]["/payments/{payment_id}/refund"]["post"]
    assert "registro de reembolso hecho fuera de shifty" in operacion["summary"].lower()
    assert "Mercado Pago" in operacion["description"]
