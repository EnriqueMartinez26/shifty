"""Historial de links retirados de un cobro (revision de perf/f4-pay, 2026-09-25).

Un cobro cambia de link cuando se regenera (cobro vencido) o se re-tarifa.
Las preferencias usan ``binary_mode``: MP aprueba o rechaza en el momento, sin
cupones de efectivo ni pagos que queden pendientes. Aun asi un pago del link
viejo puede llegar con el link nuevo ya vivo: el link retirado sigue pagable
hasta que el outbox lo vence en MP (un tick de 20 s, o mas si esa llamada
falla), un rechazo se reintenta en el mismo link, y el webhook de un pago
hecho antes del retiro puede llegar tarde, reentregarse o perderse. Este
modulo guarda cada link retirado (``PaymentLinkHistory``: referencia,
preferencia, importe y moneda de ESE link) para que el webhook y la
conciliacion puedan reconocerlo:

- ``record_retired_link``: lo anota ``service._retire_link`` al retirarlo.
- ``classify_payment_link``: dice si un pago es del link vigente, de uno
  retirado (con su fila) o de ninguno conocido.
- ``adopt_retired_link``: el cobro pasa a ser el del link retirado que se
  pago; el vigente se retira y se manda a vencer en MP.
- ``retired_link_references``: las referencias a buscar en MP en la
  conciliacion y en el rescate del job de vencimiento.

Todo corre con el turno ya lockeado y el pago leido despues (regla 7).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.payments.model import (
    EVENT_PREFERENCE_EXPIRE,
    EXTERNAL_REFERENCE_SEPARATOR,
    OutboxMessage,
    Payment,
    PaymentLinkHistory,
    external_reference_for,
    is_placeholder_preference_id,
)

logger = structlog.get_logger()

# Cuanto hacia atras la conciliacion busca en MP pagos de links retirados.
# Con ``binary_mode`` no hay cupones de efectivo pendientes: un pago de un
# link retirado se aprueba en el momento (antes del retiro o en la ventana en
# que el link sigue pagable) y lo que puede demorarse es SU aviso: un webhook
# tardio o perdido, o una reentrega. La conciliacion corre cada 2 minutos
# (``core/celery_app.py``), asi que una semana cubre esos casos con margen y
# acota la busqueda de cada corrida (una request a MP por link retirado). El webhook no usa la
# ventana: reconoce un link retirado del historial a cualquier edad.
RETIRED_LINK_SEARCH_DAYS = 7

# Cuantos links retirados por cobro busca la conciliacion en MP, los mas
# recientes (revision de e5579b6..3b977a9, #1). Sin tope, un cobro regenerado
# muchas veces hacia 1 + N busquedas y se comia el presupuesto de la fase A y
# los limites de Celery: con 2, a lo sumo 3 busquedas por cobro. Un pago de un
# link mas viejo lo sigue reconociendo el webhook (que no usa este tope).
RETIRED_LINK_SEARCH_MAX = 2

TipoDeLink = Literal["vigente", "retirado", "desconocido"]


@dataclass(frozen=True)
class LinkDelPago:
    """De que link del cobro es un pago."""

    tipo: TipoDeLink
    retirado: PaymentLinkHistory | None = None


def _link_ref_de(referencia: str) -> str | None:
    """El nonce de una referencia ``<turno>:<link_ref>``; None si es legada."""
    if EXTERNAL_REFERENCE_SEPARATOR not in referencia:
        return None
    return referencia.split(EXTERNAL_REFERENCE_SEPARATOR, 1)[1] or None


@dataclass(frozen=True)
class ImportesDelLink:
    """Importe de un link y lo que lo explica (promo, descuento). Se toma
    ANTES de re-tarifar: el historial guarda los de ESE link, no los nuevos
    (revision de e5579b6..3b977a9, #3)."""

    amount: Decimal
    original_amount: Decimal | None
    discount_amount: Decimal | None
    promotion_code: str | None

    @classmethod
    def del_cobro(cls, payment: Payment) -> ImportesDelLink:
        return cls(
            amount=payment.amount,
            original_amount=payment.original_amount,
            discount_amount=payment.discount_amount,
            promotion_code=payment.promotion_code,
        )


def record_retired_link(
    db: AsyncSession, payment: Payment, *, importes: ImportesDelLink | None = None
) -> None:
    """Anota el link que el cobro deja de usar. Un placeholder no existe en
    MP (nadie pudo pagarlo): no se anota. ``importes``: los que cobraba ESE
    link, si el cobro ya se re-tarifo antes de retirarlo."""
    if is_placeholder_preference_id(payment.preference_id):
        return
    del_link = importes or ImportesDelLink.del_cobro(payment)
    db.add(
        PaymentLinkHistory(
            store_id=payment.store_id,
            payment_id=payment.id,
            link_ref=payment.link_ref,
            preference_id=payment.preference_id,
            amount=del_link.amount,
            original_amount=del_link.original_amount,
            discount_amount=del_link.discount_amount,
            promotion_code=del_link.promotion_code,
            currency=payment.currency,
            retired_at=datetime.now(timezone.utc),
        )
    )


async def _fila_retirada(
    db: AsyncSession,
    payment: Payment,
    *,
    link_ref: str | None,
    preference_id: str | None,
) -> PaymentLinkHistory | None:
    consulta = select(PaymentLinkHistory).where(
        PaymentLinkHistory.store_id == payment.store_id,
        PaymentLinkHistory.payment_id == payment.id,
        (
            PaymentLinkHistory.link_ref.is_(None)
            if link_ref is None
            else PaymentLinkHistory.link_ref == link_ref
        ),
    )
    if preference_id:
        consulta = consulta.where(PaymentLinkHistory.preference_id == preference_id)
    resultado = await db.execute(
        consulta.order_by(PaymentLinkHistory.retired_at.desc()).limit(1)
    )
    return resultado.scalar_one_or_none()


async def classify_payment_link(
    db: AsyncSession, payment: Payment, data: dict[str, Any], referencia: str
) -> LinkDelPago:
    """De que link del cobro es el pago (la identidad ya se valido).

    La referencia manda (``<turno>:<link_ref>``, la senal de Shifty); la
    preferencia, si MP la manda, desempata links legados con la misma
    referencia. Sin referencia se clasifica como vigente y la valida
    ``processing._validate_payment_link`` (rechaza si el cobro tiene nonce).
    """
    preferencia = str(data.get("preference_id") or "").strip() or None
    if referencia and referencia != payment.current_external_reference:
        fila = await _fila_retirada(
            db,
            payment,
            link_ref=_link_ref_de(referencia),
            preference_id=preferencia,
        )
        return LinkDelPago("retirado", fila) if fila else LinkDelPago("desconocido")
    if preferencia and payment.preference_id and preferencia != payment.preference_id:
        fila = await _fila_retirada(
            db, payment, link_ref=payment.link_ref, preference_id=preferencia
        )
        return LinkDelPago("retirado", fila) if fila else LinkDelPago("desconocido")
    return LinkDelPago("vigente")


def pays_retired_link(retirado: PaymentLinkHistory, data: dict[str, Any]) -> bool:
    """El pago es por el importe y la moneda de ESE link retirado."""
    importe = data.get("transaction_amount")
    if importe is None:
        return False
    moneda = str(data.get("currency_id") or retirado.currency).strip()
    return moneda == retirado.currency and Decimal(str(importe)).quantize(
        Decimal("0.01")
    ) == Decimal(str(retirado.amount)).quantize(Decimal("0.01"))


def adopt_retired_link(
    db: AsyncSession, payment: Payment, retirado: PaymentLinkHistory
) -> None:
    """El cobro pasa a ser el del link retirado que se pago.

    El link vigente se retira (queda en el historial) y se manda a vencer en
    MP en esta misma transaccion (``payment.preference.expire``; un
    placeholder no se publica): un solo link vivo o pagado por cobro. El
    importe del cobro pasa a ser el de ese link, la plata que entro, con su
    promo y su descuento.

    Quien la llama ya valido el pago contra ESE link: aca no hay nada que
    pueda fallar a mitad (revision de e5579b6..3b977a9, #2). Queda un log de
    info con los importes y los nonces (#3): el modulo de pagos no tiene
    auditoria propia.
    """
    logger.info(
        "payment_adopted_retired_link",
        store_id=payment.store_id,
        payment_id=payment.id,
        appointment_id=payment.appointment_id,
        previous_amount=str(payment.amount),
        amount=str(retirado.amount),
        previous_link_ref=payment.link_ref,
        link_ref=retirado.link_ref,
        previous_preference_id=payment.preference_id,
        preference_id=retirado.preference_id,
    )
    if not is_placeholder_preference_id(payment.preference_id):
        record_retired_link(db, payment)
        db.add(
            OutboxMessage(
                store_id=payment.store_id,
                event_type=EVENT_PREFERENCE_EXPIRE,
                payload={
                    "appointment_id": payment.appointment_id,
                    "payment_id": payment.id,
                    "preference_id": payment.preference_id,
                },
            )
        )
    payment.link_ref = retirado.link_ref
    payment.preference_id = retirado.preference_id
    payment.payment_link = None
    payment.amount = retirado.amount
    payment.original_amount = retirado.original_amount
    payment.discount_amount = retirado.discount_amount
    payment.promotion_code = retirado.promotion_code
    payment.currency = retirado.currency


async def retired_link_references(
    db: AsyncSession, payments: Iterable[Payment], *, ahora: datetime | None = None
) -> dict[str, list[str]]:
    """{payment.id: referencias de sus links retirados en la ventana}, del
    mas reciente al mas viejo y como mucho ``RETIRED_LINK_SEARCH_MAX`` por
    cobro. Una consulta para todo el lote (regla 12); sin la del link vigente.

    Filtra por ``store_id`` (revision de e5579b6..3b977a9, #4 e): bajo RLS el
    filtro explicito es la defensa en profundidad y el camino al indice; una
    fila de otra tienda nunca aporta una referencia a este cobro.
    """
    por_id = {payment.id: payment for payment in payments}
    if not por_id:
        return {}
    desde = (ahora or datetime.now(timezone.utc)) - timedelta(
        days=RETIRED_LINK_SEARCH_DAYS
    )
    filas = await db.execute(
        select(
            PaymentLinkHistory.payment_id,
            PaymentLinkHistory.store_id,
            PaymentLinkHistory.link_ref,
        )
        .where(
            PaymentLinkHistory.store_id.in_({p.store_id for p in por_id.values()}),
            PaymentLinkHistory.payment_id.in_(list(por_id)),
            PaymentLinkHistory.retired_at >= desde,
        )
        .order_by(PaymentLinkHistory.retired_at.desc())
    )
    referencias: dict[str, list[str]] = {}
    for payment_id, store_id, link_ref in filas.all():
        payment = por_id[str(payment_id)]
        if str(store_id) != payment.store_id:
            continue
        referencia = external_reference_for(payment.appointment_id, link_ref)
        lista = referencias.setdefault(payment.id, [])
        if (
            len(lista) < RETIRED_LINK_SEARCH_MAX
            and referencia != payment.current_external_reference
            and referencia not in lista
        ):
            lista.append(referencia)
    return referencias


__all__ = [
    "ImportesDelLink",
    "RETIRED_LINK_SEARCH_DAYS",
    "RETIRED_LINK_SEARCH_MAX",
    "LinkDelPago",
    "adopt_retired_link",
    "classify_payment_link",
    "pays_retired_link",
    "record_retired_link",
    "retired_link_references",
]
