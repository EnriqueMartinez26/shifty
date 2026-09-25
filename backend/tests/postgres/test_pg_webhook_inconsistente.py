"""Un webhook con importe inconsistente deja su fila en el inbox, contra
Postgres real (B2-04).

2026-09-16, hallazgo B2-04: la ``RuntimeError`` del validador de integridad
subia al handler generico como 500 y la transaccion no commiteaba, asi que la
fila del ``WebhookInbox`` se perdia. Aca se verifica desde OTRA conexion (rol
dueno) que la fila quedo commiteada con ``error`` y ``attempts``, con
``processed_at`` nulo (regla 7), que el pago no se toco, y que las otras
guardas del webhook siguen vivas: una firma invalida se rechaza sin crear
fila y una reentrega del mismo ``event_id`` suma un intento sobre la misma
fila en vez de duplicarla.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
from core.database import _apply_tenant_context, set_tenant_context
from modules.payments.model import Payment
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    webhook_signature_headers,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _approved_remote_payment,
    _book_with_mercadopago,
    _configure_gateway,
    _enable_payments,
    _stub_mercadopago,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres


async def _fila_del_inbox(owner_engine: AsyncEngine) -> list[tuple[Any, ...]]:
    async with owner_engine.connect() as conn:
        filas = await conn.execute(
            text(
                "select attempts, error, processed_at from webhook_inbox "
                "where event_id = 'mercadopago:evt-b204-pg'"
            )
        )
        return [tuple(f) for f in filas.all()]


async def _estado_del_pago(owner_engine: AsyncEngine, appointment_id: str) -> str:
    async with owner_engine.connect() as conn:
        estado = (
            await conn.execute(
                text("select status from payments where appointment_id = :id"),
                {"id": appointment_id},
            )
        ).scalar_one()
        return cast(str, estado)


async def _entregar(client: AsyncClient, store: str, *, secret: str) -> Any:
    return await client.post(
        f"/payments/webhooks/mercadopago?store_id={store}",
        json={"id": "evt-b204-pg", "type": "payment", "data": {"id": "mp-b204-pg"}},
        headers=webhook_signature_headers(
            secret=secret,
            data_id="mp-b204-pg",
            request_id="req-b204-pg",
            ts="1710000000",
        ),
    )


@pytest.mark.asyncio
async def test_el_evento_inconsistente_queda_commiteado_en_el_inbox_sin_aplicar(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    store, token = await register_and_login(
        client, app_sessions, slug="b204-pg", email="b204-pg@demo.com"
    )
    # Activar cobros exige la politica de sena publicada (stores/router.py,
    # DEPOSIT_POLICY_REQUIRED); la tienda de prueba nace con una, como en
    # tests/integration.
    politica = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={
            "deposit_policy": "La sena se descuenta del total y se devuelve con 24hs de aviso."
        },
    )
    assert politica.status_code == 200, politica.text
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    appointment_id = await _book_with_mercadopago(
        client, token, store, slug_suffix="b204-pg", hour=10
    )
    async with app_sessions() as db:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(db)
            payment = (
                await db.execute(
                    select(Payment).where(Payment.appointment_id == appointment_id)
                )
            ).scalar_one()
            remoto = {
                **_approved_remote_payment(payment),
                "id": "mp-b204-pg",
                "transaction_amount": float(payment.amount) / 2,
            }
        finally:
            set_tenant_context(None, False)
    _stub_mercadopago(monkeypatch, remote_payment=remoto)

    respuesta = await _entregar(client, store, secret="secret-demo")
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo.get("data", cuerpo) == {"received": True, "applied": False}

    filas = await _fila_del_inbox(owner_engine)
    assert len(filas) == 1, filas
    intentos, error, procesado = filas[0]
    assert intentos == 1 and error and procesado is None, filas
    assert await _estado_del_pago(owner_engine, appointment_id) == "pending"

    # HMAC intacto: una firma invalida se rechaza y no toca el inbox.
    rechazada = await _entregar(client, store, secret="otro-secreto")
    assert 400 <= rechazada.status_code < 500, rechazada.text
    assert await _fila_del_inbox(owner_engine) == filas

    # Idempotencia por event_id: la reentrega suma un intento, no una fila.
    reentrega = await _entregar(client, store, secret="secret-demo")
    assert reentrega.status_code == 200, reentrega.text
    filas = await _fila_del_inbox(owner_engine)
    assert len(filas) == 1 and filas[0][0] == 2 and filas[0][2] is None, filas
    assert await _estado_del_pago(owner_engine, appointment_id) == "pending"
