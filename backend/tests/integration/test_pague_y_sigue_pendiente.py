"""Pague y sigue pendiente: reintento corto del webhook y conciliacion a demanda.

F1-21 (plan de rendimiento, R9-09, decision 20, 2026-09-24). Si el webhook en
linea no se podia aplicar (MP no respondia el detalle, importe raro), el
cobro esperaba al beat del inbox (60-120 s) o a la conciliacion (5-6 min)
mientras la pagina del cliente consultaba el estado cada 2 s.

- Tras un fallo del apply en linea, el inbox se encola con ``countdown=15``
  por ``core.enqueue.enqueue`` (nunca congela el request si el broker cae).
- Si el poll publico ve un cobro de MP pendiente hace mas de 20 s, pide la
  conciliacion de ESE cobro, una vez cada 15 s por cobro (``SET NX EX 15``
  en el Redis de estado). La tarea no respeta la edad minima de la
  conciliacion general: el cliente ya dijo que pago.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from core.config import settings
import modules.payments.on_demand as on_demand
from modules.payments.jobs import reconcile_one_payment
from modules.payments.model import (
    WEBHOOK_INBOX_MAX_ATTEMPTS,
    Payment,
    PaymentStatus,
    WebhookInbox,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
    webhook_signature_headers,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _configure_gateway,
    _enable_payments,
    _stub_mercadopago,
)


class _Cola:
    def __init__(self) -> None:
        self.encolados: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def __call__(
        self, task: Any, *args: Any, options: Any = None, **kwargs: Any
    ) -> bool:
        self.encolados.append((task.name, args, dict(options or {})))
        return True


@pytest.mark.asyncio
async def test_un_webhook_que_no_se_aplico_reintenta_el_inbox_a_los_15_s(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cola = _Cola()
    monkeypatch.setattr(on_demand, "enqueue", cola)
    store_public_id, token = await register_and_login(
        client, slug="f121-webhook", email="f121-webhook@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)

    for clave in ("a", "b"):
        respuesta = await _webhook(client, store_public_id, clave)
        assert respuesta.status_code == 200, respuesta.text
        cuerpo = respuesta.json()
        assert cuerpo.get("data", cuerpo)["applied"] is False

    # Revision de f2b: una rafaga de webhooks fallidos de la misma tienda
    # encola UN reintento cada 30 s (SET NX EX 30 por tienda).
    assert cola.encolados == [("process_payment_webhook_inbox", (), {"countdown": 15})]


async def _webhook(client: AsyncClient, store_public_id: str, clave: str) -> Any:
    return await client.post(
        f"/payments/webhooks/mercadopago?store_id={store_public_id}",
        json={"id": f"evt-f121-{clave}", "type": "payment", "data": {"id": clave}},
        headers=webhook_signature_headers(
            secret="secret-demo",
            data_id=clave,
            request_id=f"req-f121-{clave}",
            ts="1710000000",
        ),
    )


@pytest.mark.asyncio
async def test_un_webhook_con_los_intentos_agotados_no_encola_reintento(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    cola = _Cola()
    monkeypatch.setattr(on_demand, "enqueue", cola)
    store_public_id, token = await register_and_login(
        client, slug="f121-agotado", email="f121-agotado@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    await _webhook(client, store_public_id, "x")
    await test_session.execute(
        update(WebhookInbox).values(attempts=WEBHOOK_INBOX_MAX_ATTEMPTS - 1)
    )
    await test_session.commit()
    cola.encolados.clear()
    # Sin deduplicacion: lo unico que puede frenar el reintento es el techo.
    import tests.conftest as raiz

    monkeypatch.setattr(raiz.MockRedis, "set", _set_sin_dedup)

    respuesta = await _webhook(client, store_public_id, "x")

    assert respuesta.status_code == 200, respuesta.text
    assert cola.encolados == []


async def _set_sin_dedup(self: Any, key: str, value: object, **_: Any) -> bool:
    return True


async def _cobro_pendiente(
    client: AsyncClient, test_session: AsyncSession, slug: str
) -> tuple[str, str]:
    store_public_id, token = await register_and_login(
        client, slug=slug, email=f"{slug}@test.com"
    )
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    servicio = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="percent",
        deposit_amount=30,
    )
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=14, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente F121",
            "client_phone": "+5491155512121",
            "payment_method": "mercadopago",
            "accepts_terms": True,
            "idempotency_key": f"{slug}-reserva",
        },
    )
    assert reserva.status_code == 201, reserva.text
    return store_public_id, cast(str, reserva.json()["payment_public_id"])


async def _envejecer(session: AsyncSession, payment_id: str, segundos: int) -> None:
    await session.execute(
        update(Payment)
        .where(Payment.id == payment_id)
        .values(created_at=datetime.now(timezone.utc) - timedelta(seconds=segundos))
    )
    await session.commit()


async def _estado(client: AsyncClient, store_public_id: str, payment_id: str) -> str:
    respuesta = await client.get(
        f"/public/payments/{payment_id}/status",
        params={"store_public_id": store_public_id},
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    return cast(str, cuerpo.get("data", cuerpo)["payment_status"])


@pytest.mark.asyncio
async def test_el_poll_pide_conciliar_un_cobro_pendiente_una_vez_cada_15_s(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    cola = _Cola()
    monkeypatch.setattr(on_demand, "enqueue", cola)
    store_public_id, cobro = await _cobro_pendiente(client, test_session, "f121-poll")

    # Recien creado: el webhook todavia puede llegar solo.
    assert await _estado(client, store_public_id, cobro) == "pending"
    assert cola.encolados == []

    await _envejecer(test_session, cobro, 30)
    for _ in range(3):
        assert await _estado(client, store_public_id, cobro) == "pending"

    # Tres polls en la misma ventana de 15 s: una sola conciliacion, que vence
    # en la cola a los 15 s (el poll la vuelve a pedir si hace falta).
    assert cola.encolados == [
        ("reconcile_payment_on_demand", (cobro,), {"expires": 15})
    ]

    # Pasada la edad minima de la conciliacion general, el lote lo cubre.
    cola.encolados.clear()
    await _envejecer(
        test_session, cobro, settings.RECONCILIATION_MIN_AGE_MINUTES * 60 + 5
    )
    import tests.conftest as raiz

    monkeypatch.setattr(raiz.MockRedis, "set", _set_sin_dedup)
    assert await _estado(client, store_public_id, cobro) == "pending"
    assert cola.encolados == []


@pytest.mark.asyncio
async def test_la_conciliacion_a_demanda_aplica_el_cobro_sin_edad_minima(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    _store, cobro_id = await _cobro_pendiente(client, test_session, "f121-job")
    await _envejecer(test_session, cobro_id, 30)
    cobro = (
        await test_session.execute(select(Payment).where(Payment.id == cobro_id))
    ).scalar_one()
    _stub_mercadopago(
        monkeypatch,
        remote_payment={
            "id": "mp-f121",
            "status": "approved",
            "external_reference": cobro.appointment_id,
            "preference_id": cobro.preference_id,
            "transaction_amount": float(cobro.amount),
            "currency_id": cobro.currency,
        },
    )

    resultado = await reconcile_one_payment(test_session, cobro_id)

    assert resultado == {"reconciled": 1, "failed": 0, "inspected": 1}, resultado
    await test_session.refresh(cobro)
    assert cobro.status == PaymentStatus.APPROVED.value
