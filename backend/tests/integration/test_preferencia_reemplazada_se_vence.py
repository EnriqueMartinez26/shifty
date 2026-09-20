"""Una preferencia de Mercado Pago que se reemplaza se manda a vencer.

2026-09-20, AUD2-B2-03: ``payment.preference.expire`` se publicaba desde un
solo lugar (``AppointmentService.release_pending``). Los demas caminos que
descartan un ``preference_id`` real dejaban el checkout viejo vivo en MP:

1. regenerar el link del panel con otro importe (el placeholder pisa el id
   real y la fase 2 pide una preferencia nueva): dos checkouts vivos para el
   mismo turno, con importes distintos;
2. confirmar a mano con un importe explicito (mismo camino).

Si el cliente paga el link viejo, ``_validate_payment_integrity`` lo rechaza
por preferencia y por importe: 10 reintentos del inbox y a ``failed_webhooks``.
La plata entro a la cuenta de la tienda y Shifty no la registra.

Queda FUERA el tercer camino del informe (desconectar la cuenta de Mercado
Pago con cobros pendientes): ahi la config con el token se borra en el mismo
pedido, asi que vencer los links exigiria salir a Mercado Pago con la
transaccion del request abierta (regla 5) y sin tope de llamadas. Que pasa con
esos cobros es decision del dueno; el informe lo deja como pregunta abierta.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from modules.payments.model import OutboxMessage, Payment
from modules.payments.service import EVENT_PREFERENCE_EXPIRE
from modules.services.model import Service
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _book_with_mercadopago,
    _configure_gateway,
    _enable_payments,
)


def _mercadopago(monkeypatch: pytest.MonkeyPatch, llamadas: list[str]) -> None:
    """Cada preferencia nueva tiene id propio; anota tambien los PUT de vencimiento."""

    async def fake(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if method == "POST" and path.startswith("/checkout/preferences"):
            n = len([x for x in llamadas if x.startswith("POST")]) + 1
            llamadas.append(f"POST /checkout/preferences -> pref-{n}")
            return {
                "id": f"pref-{n}",
                "init_point": f"https://www.mercadopago.com/checkout/v1/redirect?p={n}",
            }
        llamadas.append(f"{method} {path}")
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake)


async def _vencimientos(session: AsyncSession) -> list[dict[str, Any]]:
    session.expire_all()
    filas = (
        (
            await session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == EVENT_PREFERENCE_EXPIRE
                )
            )
        )
        .scalars()
        .all()
    )
    return [dict(m.payload or {}) for m in filas]


async def _turno_del_panel(
    client: AsyncClient, slug: str, hour: int
) -> tuple[str, str]:
    """Turno del panel sin sena: su cobro no tiene snapshot deposit_rule."""
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
                hour=hour, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": f"{slug}-turno",
        },
    )
    assert reserva.status_code == 201, reserva.text
    return token, cast(str, reserva.json()["public_id"])


async def _turno_con_link(
    client: AsyncClient, session: AsyncSession, slug: str, hour: int
) -> tuple[str, str]:
    """(token, turno) de una reserva publica con sena y link real de MP."""
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix=slug, hour=hour
    )
    pago = (
        await session.execute(select(Payment).where(Payment.appointment_id == turno))
    ).scalar_one()
    assert pago.preference_id == "pref-1"
    return token, turno


@pytest.mark.asyncio
async def test_regenerar_el_link_con_otro_importe_vence_la_preferencia_vieja(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cobro del panel (sin snapshot de sena): sube el precio y se re-tarifa."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    llamadas: list[str] = []
    _mercadopago(monkeypatch, llamadas)
    token, turno = await _turno_del_panel(client, "aud2-03-panel", 10)

    primero = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(token)
    )
    assert primero.status_code == 200, primero.text
    assert primero.json()["preference_id"] == "pref-1"

    await test_session.execute(update(Service).values(price=20000))
    await test_session.commit()

    segundo = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(token)
    )
    assert segundo.status_code == 200, segundo.text
    assert segundo.json()["preference_id"] == "pref-2"

    vencimientos = await _vencimientos(test_session)
    assert [v.get("preference_id") for v in vencimientos] == ["pref-1"], vencimientos
    assert vencimientos[0]["appointment_id"] == turno


@pytest.mark.asyncio
async def test_confirmar_a_mano_con_otro_importe_vence_la_preferencia_vieja(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    llamadas: list[str] = []
    _mercadopago(monkeypatch, llamadas)
    token, turno = await _turno_con_link(client, test_session, "aud2-03-manual", 11)

    confirmado = await client.post(
        f"/payments/{turno}/manual-confirm",
        headers=auth_headers(token),
        json={"amount": "5000.00"},
    )
    assert confirmado.status_code == 200, confirmado.text

    vencimientos = await _vencimientos(test_session)
    assert [v.get("preference_id") for v in vencimientos] == ["pref-1"], vencimientos


@pytest.mark.asyncio
async def test_un_placeholder_no_genera_vencimiento(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Solo se vence un id REAL: un placeholder no existe en Mercado Pago."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    llamadas: list[str] = []
    _mercadopago(monkeypatch, llamadas)
    store, token = await register_and_login(
        client, slug="aud2-03-placeholder", email="aud2-03-placeholder@t.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix="aud2-03-placeholder", hour=13
    )
    # El cobro vuelve al placeholder, como si MP nunca hubiera respondido.
    await test_session.execute(
        update(Payment)
        .where(Payment.appointment_id == turno)
        .values(
            preference_id=f"pref_{turno}",
            payment_link=f"https://payments.shifty.local/pay/{turno}",
        )
    )
    await test_session.commit()

    respuesta = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(token)
    )
    assert respuesta.status_code == 200, respuesta.text
    assert await _vencimientos(test_session) == []
