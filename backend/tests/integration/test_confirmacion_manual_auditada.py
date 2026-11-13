"""Confirmar un cobro a mano deja auditoria y rechaza un importe en cero.

2026-11-09, issue #278: ``POST /payments/{appointment}/manual-confirm`` tomaba
cualquier importe ``>= 0`` y no escribia auditoria, mientras que registrar el
resto (``_audit_remainder``) si. Una tienda que confirma senas por WhatsApp a
mano no dejaba rastro de quien registro que, ni de cuanto se aparto el importe
del esperado.

La auditoria guarda el hecho de las notas (si hay y su largo), nunca el texto:
``audit_logs`` no se purga nunca (L3-02, BE-15). El texto queda en el
``raw_payload`` del cobro.

Que pasa con un importe menor a la sena esperada sigue pendiente de decision
de producto (#278): aca solo se fija que sigue funcionando como hoy.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.audit.model import AuditLog
from modules.payments.model import OutboxMessage, Payment, PaymentStatus
from modules.payments.service import (
    NonPositivePreferenceAmountError,
    prepare_mercadopago_preference,
)
from tests.integration.test_confirmacion_manual_sin_retarifar import _turno_con_sena
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import _stub_preference


async def _cobro(session: AsyncSession, turno: str) -> Payment:
    session.expire_all()
    return (
        await session.execute(select(Payment).where(Payment.appointment_id == turno))
    ).scalar_one()


async def _auditoria_de_cobros(session: AsyncSession) -> list[AuditLog]:
    session.expire_all()
    return list(
        (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.resource_type == "Payment")
                .order_by(AuditLog.id)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_confirmar_a_mano_deja_auditoria_con_importes_y_sin_el_texto(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_preference(monkeypatch)
    slug = "aud-278-menor"
    token, turno, pago = await _turno_con_sena(client, test_session, slug, 10)
    sena = pago.amount
    menor = (sena / 2).quantize(Decimal("0.01"))
    nota = "pago por transferencia, comprobante 1234"

    confirmado = await client.post(
        f"/payments/{turno}/manual-confirm",
        headers=auth_headers(token),
        json={"amount": str(menor), "notes": nota},
    )

    # Un importe menor sigue pasando: esa politica esta pendiente (#278).
    assert confirmado.status_code == 200, confirmado.text
    cobro = await _cobro(test_session, turno)
    assert cobro.status == PaymentStatus.MANUAL_CONFIRMED.value
    assert cobro.amount == menor
    cobro_id, tienda_id = cobro.id, cobro.store_id

    filas = await _auditoria_de_cobros(test_session)
    assert len(filas) == 1
    fila = filas[0]
    assert fila.action == "status_change"
    assert fila.resource_id == cobro_id
    assert fila.store_id == tienda_id
    assert fila.actor_email == f"{slug}@t.com"
    assert fila.payload_before == {
        "status": PaymentStatus.PENDING.value,
        "amount": str(sena),
    }
    assert fila.payload_after == {
        "appointment_id": turno,
        "status": PaymentStatus.MANUAL_CONFIRMED.value,
        "expected_amount": str(sena),
        "recorded_amount": str(menor),
        "amount_overridden": True,
        "notes_present": True,
        "notes_length": len(nota),
    }
    # El texto de la nota nunca llega a audit_logs (L3-02).
    assert nota not in str(fila.payload_before) + str(fila.payload_after)


@pytest.mark.asyncio
async def test_sin_importe_audita_el_esperado_y_el_doble_clic_no_suma_filas(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_preference(monkeypatch)
    token, turno, pago = await _turno_con_sena(client, test_session, "aud-278-sin", 11)
    sena = pago.amount

    for _ in range(2):
        respuesta = await client.post(
            f"/payments/{turno}/manual-confirm", headers=auth_headers(token), json={}
        )
        assert respuesta.status_code == 200, respuesta.text

    filas = await _auditoria_de_cobros(test_session)
    # La segunda es un no-op sobre un cobro acreditado: no escribe nada.
    assert len(filas) == 1
    assert filas[0].payload_after == {
        "appointment_id": turno,
        "status": PaymentStatus.MANUAL_CONFIRMED.value,
        "expected_amount": str(sena),
        "recorded_amount": str(sena),
        "amount_overridden": False,
        "notes_present": False,
        "notes_length": 0,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("importe", ["0", "0.00", "-1"])
async def test_un_importe_no_positivo_es_422_y_no_toca_el_cobro(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    importe: str,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_preference(monkeypatch)
    token, turno, pago = await _turno_con_sena(
        client, test_session, f"aud-278-cero-{importe.replace('.', '')}", 12
    )
    sena = pago.amount

    respuesta = await client.post(
        f"/payments/{turno}/manual-confirm",
        headers=auth_headers(token),
        json={"amount": importe},
    )

    assert respuesta.status_code == 422, respuesta.text
    cobro = await _cobro(test_session, turno)
    assert cobro.status == PaymentStatus.PENDING.value
    assert cobro.amount == sena
    assert await _auditoria_de_cobros(test_session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("importe", [Decimal("0"), Decimal("-0.01")])
async def test_no_se_prepara_una_preferencia_por_un_importe_no_positivo(
    test_session: AsyncSession, importe: Decimal
) -> None:
    """La guarda corre antes de toda lectura: ni gateway, ni tienda, ni pagador.

    Los demas argumentos no se tocan, asi que alcanza con relleno.
    """
    with pytest.raises(NonPositivePreferenceAmountError):
        await prepare_mercadopago_preference(
            test_session,
            payment=object(),  # type: ignore[arg-type]
            appointment=object(),  # type: ignore[arg-type]
            service=object(),  # type: ignore[arg-type]
            store_id="no-store",
            amount=importe,
            link_ref=None,
        )


@pytest.mark.asyncio
async def test_confirmar_a_mano_un_cobro_reembolsado_responde_409_sin_mutaciones(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_preference(monkeypatch)
    token, turno, pago = await _turno_con_sena(
        client, test_session, "aud-299-reembolsado", 14
    )
    assert pago.apply_status(PaymentStatus.APPROVED.value)
    assert pago.apply_status(PaymentStatus.REFUNDED.value)
    pago.original_amount = Decimal("12000.00")
    pago.discount_amount = Decimal("1500.00")
    pago.promotion_code = "PROMO299"
    pago.link_ref = "refund-link-299"
    pago.external_payment_id = "mp-refund-299"
    pago.transaction_id = "txn-refund-299"
    await test_session.commit()

    async def snapshot() -> tuple[dict[str, object], list[tuple[str, object]], int]:
        test_session.expire_all()
        current = (
            await test_session.execute(
                select(Payment).where(Payment.appointment_id == turno)
            )
        ).scalar_one()
        outbox = list(
            (
                await test_session.execute(
                    select(OutboxMessage.event_type, OutboxMessage.payload)
                    .order_by(OutboxMessage.id)
                )
            ).all()
        )
        audits = await test_session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.resource_type == "Payment", AuditLog.resource_id == current.id
            )
        )
        return (
            {
                "status": current.status,
                "amount": current.amount,
                "original_amount": current.original_amount,
                "discount_amount": current.discount_amount,
                "promotion_code": current.promotion_code,
                "preference_id": current.preference_id,
                "payment_link": current.payment_link,
                "link_ref": current.link_ref,
                "external_payment_id": current.external_payment_id,
                "transaction_id": current.transaction_id,
                "deposit_rule": current.deposit_rule,
            },
            outbox,
            audits or 0,
        )

    before = await snapshot()
    for _ in range(2):
        respuesta = await client.post(
            f"/payments/{turno}/manual-confirm",
            headers=auth_headers(token),
            json={"amount": "5000.00", "notes": "no debe registrarse"},
        )

        assert respuesta.status_code == 409, respuesta.text
        assert respuesta.json()["error_code"] == (
            "PAYMENT_REFUNDED_CANNOT_BE_MANUALLY_CONFIRMED"
        )
        assert await snapshot() == before


@pytest.mark.asyncio
async def test_confirmar_a_mano_un_cobro_vencido_sigue_permitido(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_preference(monkeypatch)
    token, turno, pago = await _turno_con_sena(
        client, test_session, "aud-299-vencido", 15
    )
    assert pago.apply_status(PaymentStatus.EXPIRED.value)
    await test_session.commit()

    respuesta = await client.post(
        f"/payments/{turno}/manual-confirm", headers=auth_headers(token), json={}
    )

    assert respuesta.status_code == 200, respuesta.text
    cobro = await _cobro(test_session, turno)
    assert cobro.status == PaymentStatus.MANUAL_CONFIRMED.value
