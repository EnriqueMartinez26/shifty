"""El webhook de Mercado Pago no acredita nada que MP no haya confirmado.

2026-10-02, auditoria de origin/main. La firma HMAC de MP cubre solo
``data.id``, ``x-request-id`` y ``ts``: el resto del cuerpo no esta firmado y
lo puede escribir cualquiera que reenvie una notificacion valida. Tres huecos:

1. Si la consulta ``GET /v1/payments/{id}`` fallaba o volvia vacia,
   ``enrich_mercadopago_webhook_payload`` devolvia el cuerpo crudo y el
   webhook (y el lote del inbox) aplicaba el estado que trajera. Sintoma: con
   MP caido, un cuerpo con ``data.status = approved`` acreditaba el cobro y
   confirmaba el turno sin que MP lo dijera.
2. Un ``approved`` sin ``transaction_amount`` salteaba el control de importe,
   y sin ``collector_id`` (o con la tienda sin ``oauth_user_id``) el de la
   cuenta. Sintoma: se acreditaba sin saber cuanto se pago ni a quien.
3. ``live_mode`` se pedia a MP y no se miraba. Sintoma: en produccion un pago
   de sandbox acreditaba un cobro real.

Regla 7: lo que no se aplica queda en el inbox sin ``processed_at`` y se
reintenta hasta ``WEBHOOK_INBOX_MAX_ATTEMPTS``; el motivo queda en ``error``
(visible para el dueno en ``failed_webhooks``), como cualquier otra falla de
integridad (B2-04).

SQLite alcanza: el cambio no toca locks ni el orden turno -> pago; decide si
aplicar ANTES de escribir, con el turno y el pago ya lockeados como siempre.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.config import Environment, settings
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.jobs import process_webhook_inbox_batch
from modules.payments.model import (
    Payment,
    PaymentGatewayConfig,
    PaymentStatus,
    WebhookInbox,
)
from modules.payments.processing import apply_mercadopago_webhook_payload
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
    webhook_signature_headers,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _book_with_mercadopago,
    _configure_gateway,
    _enable_payments,
    _stub_mercadopago,
)

CUENTA = "COLLECTOR-TIENDA"


@dataclass(frozen=True)
class _Cobro:
    """Lo que los tests leen del cobro, copiado antes de cualquier commit (un
    atributo expirado en una sesion async no se puede releer de forma
    perezosa)."""

    id: str
    turno: str
    store_id: str
    referencia: str
    importe: float
    moneda: str
    preferencia: str | None


def _mp_caido(monkeypatch: pytest.MonkeyPatch, *, falla: str) -> None:
    """La consulta del pago falla (excepcion) o vuelve vacia."""

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if falla == "excepcion":
            raise RuntimeError("Mercado Pago no responde")
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


async def _cobro_pendiente(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    slug: str,
) -> tuple[str, _Cobro]:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@test.com")
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    turno = await _book_with_mercadopago(
        client, token, store, slug_suffix=slug, hour=10
    )
    cobro = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == turno)
        )
    ).scalar_one()
    return store, _Cobro(
        id=cobro.id,
        turno=cobro.appointment_id,
        store_id=cobro.store_id,
        referencia=cobro.current_external_reference,
        importe=float(cobro.amount),
        moneda=cobro.currency,
        preferencia=cobro.preference_id,
    )


def _cuerpo_aprobado(cobro: _Cobro, *, evento: str, pago: str) -> dict[str, Any]:
    """Un cuerpo de webhook que DICE aprobado, con todo lo que la integridad
    mira: nada de esto esta cubierto por la firma."""
    return {
        "id": evento,
        "type": "payment",
        "action": "payment.updated",
        "data": {
            "id": pago,
            "status": "approved",
            "external_reference": cobro.referencia,
            "transaction_amount": cobro.importe,
            "currency_id": cobro.moneda,
            "collector_id": CUENTA,
            "live_mode": True,
            "metadata": {
                "appointment_id": cobro.turno,
                "payment_id": cobro.id,
                "store_id": cobro.store_id,
            },
        },
    }


def _remoto_aprobado(cobro: _Cobro, **cambios: Any) -> dict[str, Any]:
    remoto: dict[str, Any] = {
        "id": "mp-remoto",
        "status": "approved",
        "external_reference": cobro.referencia,
        "preference_id": cobro.preferencia,
        "transaction_amount": cobro.importe,
        "currency_id": cobro.moneda,
        "collector_id": CUENTA,
        "live_mode": True,
    }
    remoto.update(cambios)
    return {k: v for k, v in remoto.items() if v is not None}


async def _vincular_cuenta(session: AsyncSession, cobro: _Cobro) -> None:
    await session.execute(
        update(PaymentGatewayConfig)
        .where(PaymentGatewayConfig.store_id == cobro.store_id)
        .values(oauth_user_id=CUENTA)
    )
    await session.commit()


async def _sigue_pendiente(session: AsyncSession, cobro: _Cobro) -> None:
    session.expire_all()
    pago = (
        await session.execute(select(Payment).where(Payment.id == cobro.id))
    ).scalar_one()
    assert pago.status == PaymentStatus.PENDING.value
    assert pago.external_payment_id is None
    turno = (
        await session.execute(select(Appointment).where(Appointment.id == cobro.turno))
    ).scalar_one()
    assert turno.status == AppointmentStatus.PENDING_PAYMENT.value


async def _entregar(
    client: AsyncClient, store: str, cuerpo: dict[str, Any]
) -> dict[str, Any]:
    pago = str(cuerpo["data"]["id"])
    respuesta = await client.post(
        f"/payments/webhooks/mercadopago?store_id={store}",
        json=cuerpo,
        headers=webhook_signature_headers(
            secret="secret-demo",
            data_id=pago,
            request_id=f"req-{cuerpo['id']}",
            ts="1710000000",
        ),
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo_respuesta = respuesta.json()
    datos: dict[str, Any] = cuerpo_respuesta.get("data", cuerpo_respuesta)
    return datos


async def _inbox(session: AsyncSession) -> WebhookInbox:
    session.expire_all()
    return (await session.execute(select(WebhookInbox))).scalar_one()


# --- 1. Sin respuesta de MP no se aplica el cuerpo ----------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("falla", ["excepcion", "vacia"])
async def test_con_mp_caido_el_webhook_no_aplica_el_estado_del_cuerpo(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    falla: str,
) -> None:
    store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, f"cuerpo-http-{falla}"
    )
    _mp_caido(monkeypatch, falla=falla)

    datos = await _entregar(
        client, store, _cuerpo_aprobado(cobro, evento="evt-cuerpo", pago="mp-cuerpo")
    )

    assert datos == {"received": True, "applied": False}, (
        "el estado salio del cuerpo sin firmar: MP nunca confirmo el pago"
    )
    await _sigue_pendiente(test_session, cobro)
    inbox = await _inbox(test_session)
    assert inbox.processed_at is None, "tiene que quedar para el reintento"
    assert inbox.attempts == 1
    assert "mercado pago" in (inbox.error or "").lower(), inbox.error


@pytest.mark.asyncio
@pytest.mark.parametrize("falla", ["excepcion", "vacia"])
async def test_con_mp_caido_el_inbox_no_aplica_el_estado_del_cuerpo(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    falla: str,
) -> None:
    _store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, f"cuerpo-inbox-{falla}"
    )
    test_session.add(
        WebhookInbox(
            store_id=cobro.store_id,
            provider="mercadopago",
            event_id="mercadopago:evt-inbox-cuerpo",
            event_type="payment",
            payload=_cuerpo_aprobado(
                cobro, evento="evt-inbox-cuerpo", pago="mp-inbox-cuerpo"
            ),
        )
    )
    await test_session.commit()
    _mp_caido(monkeypatch, falla=falla)

    resultado = await process_webhook_inbox_batch(test_session)

    assert resultado["processed"] == 0, resultado
    assert resultado["failed"] == 1, resultado
    await _sigue_pendiente(test_session, cobro)
    inbox = await _inbox(test_session)
    assert inbox.processed_at is None
    assert inbox.attempts == 1
    assert "mercado pago" in (inbox.error or "").lower(), inbox.error


@pytest.mark.asyncio
async def test_si_mp_responde_se_aplica_lo_que_dice_mp_no_el_cuerpo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MP dice ``rejected`` y el cuerpo ``approved``: gana MP. Y si MP no manda
    estado, el del cuerpo no lo completa."""
    store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "cuerpo-vs-mp"
    )
    _stub_mercadopago(monkeypatch, remote_payment=_remoto_aprobado(cobro, status=None))

    datos = await _entregar(
        client, store, _cuerpo_aprobado(cobro, evento="evt-sin-estado", pago="mp-x")
    )

    assert datos["applied"] is False
    await _sigue_pendiente(test_session, cobro)


# --- 2. Un aprobado sin importe o sin cuenta cobradora no pasa ---------------


@pytest.mark.asyncio
async def test_aprobado_sin_importe_no_se_aplica(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "sin-importe"
    )
    _stub_mercadopago(
        monkeypatch, remote_payment=_remoto_aprobado(cobro, transaction_amount=None)
    )

    datos = await _entregar(
        client, store, {"id": "evt-sin-importe", "data": {"id": "mp-remoto"}}
    )

    assert datos["applied"] is False, "se acredito sin saber cuanto se pago"
    await _sigue_pendiente(test_session, cobro)
    inbox = await _inbox(test_session)
    assert inbox.processed_at is None
    assert "importe" in (inbox.error or "").lower(), inbox.error


@pytest.mark.asyncio
async def test_aprobado_sin_cuenta_cobradora_no_se_aplica(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "sin-collector"
    )
    await _vincular_cuenta(test_session, cobro)
    _stub_mercadopago(
        monkeypatch, remote_payment=_remoto_aprobado(cobro, collector_id=None)
    )

    datos = await _entregar(
        client, store, {"id": "evt-sin-collector", "data": {"id": "mp-remoto"}}
    )

    assert datos["applied"] is False, "se acredito sin saber a quien se pago"
    await _sigue_pendiente(test_session, cobro)
    inbox = await _inbox(test_session)
    assert inbox.processed_at is None
    assert "cuenta" in (inbox.error or "").lower(), inbox.error


@pytest.mark.asyncio
async def test_en_produccion_sin_cuenta_vinculada_no_se_acredita(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin ``oauth_user_id`` no hay contra que comparar el collector. Fuera de
    produccion es el modo manual (token pegado a mano); en produccion la
    cuenta solo se vincula por OAuth, asi que es un cobro sin dueno verificable."""
    _store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "prod-sin-oauth"
    )
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)
    remoto = _remoto_aprobado(cobro)

    with pytest.raises(RuntimeError, match="cuenta"):
        await apply_mercadopago_webhook_payload(
            test_session,
            store_id=cobro.store_id,
            payload={"data": remoto, "status": remoto["status"]},
        )
    await test_session.rollback()
    await _sigue_pendiente(test_session, cobro)


# --- 3. En produccion un pago de sandbox no acredita -------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("live_mode", [False, None])
async def test_en_produccion_un_pago_de_prueba_no_se_aplica(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    live_mode: bool | None,
) -> None:
    _store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, f"prod-sandbox-{live_mode}"
    )
    await _vincular_cuenta(test_session, cobro)
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)
    remoto = _remoto_aprobado(cobro, live_mode=live_mode)

    with pytest.raises(RuntimeError, match="prueba"):
        await apply_mercadopago_webhook_payload(
            test_session,
            store_id=cobro.store_id,
            payload={"data": remoto, "status": remoto["status"]},
        )
    await test_session.rollback()
    await _sigue_pendiente(test_session, cobro)


@pytest.mark.asyncio
async def test_en_produccion_un_pago_real_y_completo_se_aplica(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda del camino feliz: las tres compuertas no frenan un pago bueno."""
    _store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "prod-real"
    )
    await _vincular_cuenta(test_session, cobro)
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)
    remoto = _remoto_aprobado(cobro)

    assert await apply_mercadopago_webhook_payload(
        test_session,
        store_id=cobro.store_id,
        payload={"data": remoto, "status": remoto["status"]},
    )
    await test_session.commit()
    test_session.expire_all()
    pago = (
        await test_session.execute(select(Payment).where(Payment.id == cobro.id))
    ).scalar_one()
    assert pago.status == PaymentStatus.APPROVED.value


@pytest.mark.asyncio
async def test_fuera_de_produccion_un_pago_de_prueba_se_aplica(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El sandbox tiene que seguir andando en desarrollo y staging."""
    store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "dev-sandbox"
    )
    _stub_mercadopago(
        monkeypatch, remote_payment=_remoto_aprobado(cobro, live_mode=False)
    )

    datos = await _entregar(
        client, store, {"id": "evt-sandbox", "data": {"id": "mp-remoto"}}
    )

    assert datos["applied"] is True
    test_session.expire_all()
    pago = (
        await test_session.execute(select(Payment).where(Payment.id == cobro.id))
    ).scalar_one()
    assert pago.status == PaymentStatus.APPROVED.value
