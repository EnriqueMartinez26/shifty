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
from celery.exceptions import SoftTimeLimitExceeded
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.processing as processing
import modules.payments.service as payments_service
from core.config import Environment, settings
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.jobs import process_webhook_inbox_batch
from modules.payments.model import (
    WEBHOOK_INBOX_MAX_ATTEMPTS,
    Payment,
    PaymentGatewayConfig,
    PaymentStatus,
    WebhookInbox,
)
from modules.payments.processing import (
    PAGO_NO_VERIFICADO,
    apply_mercadopago_webhook_payload,
)
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
async def test_si_mp_no_manda_estado_el_del_cuerpo_no_lo_completa(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MP responde el pago SIN ``status`` y el cuerpo dice ``approved``: el
    estado del cuerpo no completa el que falta (el evento no se aplica)."""
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

    # El cuerpo SI trae importe: si volviera la mezcla con el cuerpo, el
    # importe saldria de ahi y el pago se acreditaria.
    datos = await _entregar(
        client,
        store,
        _cuerpo_aprobado(cobro, evento="evt-sin-importe", pago="mp-remoto"),
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


# --- Revision 4R de la PR #104 ------------------------------------------------


def _mp_que_registra(
    monkeypatch: pytest.MonkeyPatch, remoto: dict[str, Any] | None
) -> list[str]:
    """Como ``_stub_mercadopago``, pero anota cada ruta consultada."""
    consultas: list[str] = []

    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        consultas.append(path)
        if path.startswith("/v1/payments/search"):
            return {"results": [remoto] if remoto else []}
        if path.startswith("/v1/payments/"):
            return remoto or {}
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)
    return consultas


def _sentry(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    avisos: list[dict[str, Any]] = []

    def fake_report(exc: BaseException, **contexto: Any) -> None:
        avisos.append({"error": str(exc), **contexto})

    monkeypatch.setattr(processing, "report_exception", fake_report)
    return avisos


def _en_produccion(monkeypatch: pytest.MonkeyPatch) -> None:
    # En produccion la firma se valida con el secreto global, no con el de la
    # tienda (``_validate_mercadopago_signature``).
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)
    monkeypatch.setattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", "secret-demo")


@pytest.mark.asyncio
async def test_mp_dice_rechazado_y_el_cuerpo_aprobado_el_pago_no_se_acredita(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3 W1: con la consulta buena gana MP, aunque el cuerpo diga otra cosa."""
    store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "rechazado-vs-cuerpo"
    )
    _stub_mercadopago(
        monkeypatch, remote_payment=_remoto_aprobado(cobro, status="rejected")
    )

    await _entregar(
        client,
        store,
        _cuerpo_aprobado(cobro, evento="evt-rechazado", pago="mp-remoto"),
    )

    test_session.expire_all()
    pago = (
        await test_session.execute(select(Payment).where(Payment.id == cobro.id))
    ).scalar_one()
    assert pago.status != PaymentStatus.APPROVED.value, "acredito el cuerpo, no MP"
    assert not pago.is_accredited
    turno = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == cobro.turno)
        )
    ).scalar_one()
    assert turno.status != AppointmentStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_sin_metadata_ni_referencia_de_mp_el_cuerpo_no_las_completa(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3 W1: MP no devuelve ``metadata``, ``external_reference`` ni
    ``preference_id``; el cuerpo trae los reales. Sin ellos no se sabe de que
    cobro es el pago, y el cuerpo no puede decirlo."""
    store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "sin-metadata-mp"
    )
    _stub_mercadopago(
        monkeypatch,
        remote_payment=_remoto_aprobado(
            cobro, external_reference=None, preference_id=None
        ),
    )

    datos = await _entregar(
        client, store, _cuerpo_aprobado(cobro, evento="evt-sin-meta", pago="mp-remoto")
    )

    assert datos["applied"] is False, "el cobro salio de la metadata del cuerpo"
    await _sigue_pendiente(test_session, cobro)


@pytest.mark.asyncio
async def test_sin_estado_de_mp_el_inbox_deja_el_evento_para_reintentar(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3 W1: el caso sin ``status`` tambien por el lote del inbox."""
    _store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "sin-estado-inbox"
    )
    test_session.add(
        WebhookInbox(
            store_id=cobro.store_id,
            provider="mercadopago",
            event_id="mercadopago:evt-sin-estado-inbox",
            event_type="payment",
            payload=_cuerpo_aprobado(
                cobro, evento="evt-sin-estado-inbox", pago="mp-remoto"
            ),
        )
    )
    await test_session.commit()
    _stub_mercadopago(monkeypatch, remote_payment=_remoto_aprobado(cobro, status=None))

    resultado = await process_webhook_inbox_batch(test_session)

    assert (resultado["processed"], resultado["failed"]) == (0, 1), resultado
    await _sigue_pendiente(test_session, cobro)
    inbox = await _inbox(test_session)
    assert inbox.processed_at is None
    assert inbox.error == PAGO_NO_VERIFICADO
    assert inbox.attempts == 1


@pytest.mark.asyncio
async def test_el_corte_de_celery_en_la_consulta_a_mp_no_gasta_un_intento(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3 W2: con el ``enrich`` REAL, el soft time limit que salta en la
    consulta a MP corta el lote (se propaga) y no cuenta como fallo."""
    _store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "corte-en-enrich"
    )
    test_session.add(
        WebhookInbox(
            store_id=cobro.store_id,
            provider="mercadopago",
            event_id="mercadopago:evt-corte",
            event_type="payment",
            payload={"id": "evt-corte", "data": {"id": "mp-remoto"}},
        )
    )
    await test_session.commit()

    async def corte(*_args: Any, **_kwargs: Any) -> Any:
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", corte)

    with pytest.raises(SoftTimeLimitExceeded):
        await process_webhook_inbox_batch(test_session)

    await test_session.rollback()
    inbox = await _inbox(test_session)
    assert inbox.attempts == 0, "el corte de Celery no es un fallo del evento"
    assert inbox.processed_at is None
    assert inbox.error is None


@pytest.mark.asyncio
async def test_con_mp_caido_el_evento_agota_los_intentos_sin_aplicar_el_cuerpo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3 W3: dead letter determinista. MP no responde nunca: el evento se
    reintenta hasta ``WEBHOOK_INBOX_MAX_ATTEMPTS``, queda cerrado con el
    motivo y el cuerpo ``approved`` nunca se aplico."""
    _store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "dead-letter-mp"
    )
    test_session.add(
        WebhookInbox(
            store_id=cobro.store_id,
            provider="mercadopago",
            event_id="mercadopago:evt-dead-letter",
            event_type="payment",
            payload=_cuerpo_aprobado(cobro, evento="evt-dead-letter", pago="mp-dl"),
        )
    )
    await test_session.commit()
    _mp_caido(monkeypatch, falla="excepcion")

    for _ in range(WEBHOOK_INBOX_MAX_ATTEMPTS):
        await process_webhook_inbox_batch(test_session)

    inbox = await _inbox(test_session)
    assert inbox.attempts == WEBHOOK_INBOX_MAX_ATTEMPTS
    assert inbox.processed_at is not None, "agotado, deja de reintentarse"
    assert inbox.error == PAGO_NO_VERIFICADO
    await _sigue_pendiente(test_session, cobro)


@pytest.mark.asyncio
async def test_en_produccion_un_pago_de_prueba_por_el_webhook_queda_en_el_inbox(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3 S1: el caso de ``live_mode = false`` en produccion, de punta a
    punta por el handler HTTP."""
    store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "prod-sandbox-http"
    )
    await _vincular_cuenta(test_session, cobro)
    _stub_mercadopago(
        monkeypatch, remote_payment=_remoto_aprobado(cobro, live_mode=False)
    )
    _sentry(monkeypatch)
    _en_produccion(monkeypatch)

    datos = await _entregar(
        client, store, _cuerpo_aprobado(cobro, evento="evt-prod-http", pago="mp-remoto")
    )

    assert datos == {"received": True, "applied": False}
    await _sigue_pendiente(test_session, cobro)
    inbox = await _inbox(test_session)
    assert inbox.processed_at is None
    assert inbox.attempts == 1
    assert "prueba" in (inbox.error or ""), inbox.error


@pytest.mark.asyncio
async def test_un_aprobado_rechazado_por_integridad_avisa_a_sentry_una_vez(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4 W2: una alerta por (pago de MP, motivo), con ids y sin datos
    personales. La reentrega no repite; otro motivo del mismo pago si avisa."""
    store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "alerta-integridad"
    )
    await _vincular_cuenta(test_session, cobro)
    _stub_mercadopago(
        monkeypatch, remote_payment=_remoto_aprobado(cobro, live_mode=False)
    )
    avisos = _sentry(monkeypatch)
    _en_produccion(monkeypatch)
    cuerpo = {"id": "evt-alerta", "type": "payment", "data": {"id": "mp-remoto"}}

    await _entregar(client, store, cuerpo)
    await _entregar(client, store, cuerpo)
    assert [a["motivo"] for a in avisos] == ["modo_prueba"], avisos

    _stub_mercadopago(
        monkeypatch,
        remote_payment=_remoto_aprobado(
            cobro, live_mode=False, transaction_amount=None
        ),
    )
    await _entregar(client, store, cuerpo)

    assert [a["motivo"] for a in avisos] == ["modo_prueba", "sin_importe"], avisos
    for aviso in avisos:
        assert set(aviso) == {
            "error",
            "motivo",
            "store_id",
            "payment_id",
            "mp_payment_id",
        }
        assert aviso["payment_id"] == cobro.id
        assert aviso["mp_payment_id"] == "mp-remoto"
    await _sigue_pendiente(test_session, cobro)


@pytest.mark.asyncio
async def test_un_rechazo_que_no_es_un_aprobado_no_avisa_a_sentry(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un pendiente de prueba en produccion tampoco se aplica, pero no es
    plata cobrada: queda en el inbox sin alerta."""
    store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "pendiente-de-prueba"
    )
    await _vincular_cuenta(test_session, cobro)
    _stub_mercadopago(
        monkeypatch,
        remote_payment=_remoto_aprobado(cobro, status="pending", live_mode=False),
    )
    avisos = _sentry(monkeypatch)
    _en_produccion(monkeypatch)

    datos = await _entregar(
        client,
        store,
        {"id": "evt-pend", "type": "payment", "data": {"id": "mp-remoto"}},
    )

    assert datos["applied"] is False
    assert avisos == []


@pytest.mark.asyncio
async def test_solo_se_consulta_en_mp_el_id_que_cubrio_la_firma(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1: el cuerpo no trae ``data.id`` (la firma cubre el ``data.id`` del
    query) pero si un ``payment_id`` distinto. Antes la consulta salia con el
    ``payment_id`` del cuerpo, que nadie firmo."""
    store, cobro = await _cobro_pendiente(
        client, test_session, monkeypatch, "id-firmado"
    )
    consultas = _mp_que_registra(monkeypatch, _remoto_aprobado(cobro, id="mp-firmado"))

    respuesta = await client.post(
        f"/payments/webhooks/mercadopago?store_id={store}&data.id=mp-firmado",
        json={"id": "evt-firmado", "type": "payment", "payment_id": "mp-ajeno"},
        headers=webhook_signature_headers(
            secret="secret-demo",
            data_id="mp-firmado",
            request_id="req-evt-firmado",
            ts="1710000000",
        ),
    )

    assert respuesta.status_code == 200, respuesta.text
    assert "/v1/payments/mp-firmado" in consultas, consultas
    assert not [c for c in consultas if "mp-ajeno" in c], consultas
    inbox = await _inbox(test_session)
    guardado = inbox.payload["data"]
    assert isinstance(guardado, dict) and guardado["id"] == "mp-firmado", guardado
