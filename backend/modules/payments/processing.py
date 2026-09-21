from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import NotificationType
from modules.payments.model import (
    OutboxMessage,
    Payment,
    PaymentStatus,
)
from modules.payments.model import JsonValue
from modules.services.model import Service
from modules.payments.service import (
    GatewayConfigs,
    PersistRefresh,
    fetch_mercadopago_payment,
    resolve_gateway_config,
    stamp_payment_from_status,
    sync_appointment_with_payment,
)


def resolve_payment_status(payload: dict[str, Any]) -> str | None:
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    candidate = (
        data.get("status")
        or payload.get("status")
        or payload.get("action")
        or payload.get("topic")
    )
    if not candidate:
        return None

    normalized = str(candidate).lower()
    if normalized == "payment.updated" and data.get("status"):
        normalized = str(data.get("status")).lower()

    mapping = {
        "approved": PaymentStatus.APPROVED.value,
        "accredited": PaymentStatus.APPROVED.value,
        "pending": PaymentStatus.PENDING.value,
        "in_process": PaymentStatus.PENDING.value,
        # Disputa abierta y fondos retenidos sin capturar: todavia no hay plata
        # asentada. Antes caian en "no se pudo resolver", el inbox los
        # reintentaba 10 veces y los abandonaba (AUD2-B2-04, 2026-09-20).
        "in_mediation": PaymentStatus.PENDING.value,
        "authorized": PaymentStatus.PENDING.value,
        "rejected": PaymentStatus.REJECTED.value,
        "cancelled": PaymentStatus.REJECTED.value,
        "refunded": PaymentStatus.REFUNDED.value,
        # Contracargo: la plata volvio al cliente. Contablemente es lo mismo
        # que un reembolso y el grafo ya admite approved -> refunded, asi que
        # no hace falta un estado nuevo (regla 2). Lo que si hace falta es que
        # el dueno se entere: lo avisa _notify_payment_reversed.
        "charged_back": PaymentStatus.REFUNDED.value,
        "expired": PaymentStatus.EXPIRED.value,
    }
    allowed_statuses = {status.value for status in PaymentStatus}
    return mapping.get(normalized) or (
        normalized if normalized in allowed_statuses else None
    )


async def enrich_mercadopago_webhook_payload(
    db: AsyncSession,
    *,
    store_id: str,
    payload: dict[str, Any],
    configs: GatewayConfigs | None = None,
    persist_refresh: PersistRefresh | None = None,
) -> dict[str, Any]:
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    payment_id = str(data.get("id") or payload.get("payment_id") or "").strip()
    if not payment_id:
        return payload

    try:
        payment_details = await fetch_mercadopago_payment(
            db,
            store_id=store_id,
            payment_id=payment_id,
            configs=configs,
            persist_refresh=persist_refresh,
        )
    except Exception:
        return payload

    if not payment_details:
        return payload

    merged_data = dict(data)
    merged_data.update(
        {
            "id": payment_details.get("id", merged_data.get("id")),
            "status": payment_details.get("status", merged_data.get("status")),
            "external_reference": payment_details.get(
                "external_reference", merged_data.get("external_reference")
            ),
            "metadata": payment_details.get("metadata") or merged_data.get("metadata"),
            "date_approved": payment_details.get(
                "date_approved", merged_data.get("date_approved")
            ),
            "transaction_amount": payment_details.get("transaction_amount"),
            "currency_id": payment_details.get("currency_id"),
            "collector_id": payment_details.get("collector_id"),
            "live_mode": payment_details.get("live_mode"),
            "preference_id": payment_details.get(
                "preference_id", merged_data.get("preference_id")
            ),
        }
    )
    merged_payload = dict(payload)
    merged_payload["data"] = merged_data
    merged_payload["status"] = payment_details.get("status", payload.get("status"))
    merged_payload["external_reference"] = payment_details.get(
        "external_reference",
        payload.get("external_reference"),
    )
    return merged_payload


async def find_payment_for_webhook(
    db: AsyncSession, store_id: str, payload: dict[str, Any]
) -> Payment | None:
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    raw_metadata = data.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}

    appointment_id = (
        metadata.get("appointment_id")
        or payload.get("appointment_id")
        or payload.get("external_reference")
        or data.get("external_reference")
    )
    preference_id = data.get("preference_id") or payload.get("preference_id")
    external_payment_id = (
        str(data.get("id") or payload.get("payment_id") or "").strip() or None
    )

    if external_payment_id:
        result = await db.execute(
            select(Payment)
            .where(
                Payment.store_id == store_id,
                Payment.external_payment_id == external_payment_id,
            )
            .with_for_update()
        )
        payment = result.scalar_one_or_none()
        if payment:
            return payment

    if preference_id:
        result = await db.execute(
            select(Payment)
            .where(
                Payment.store_id == store_id,
                Payment.preference_id == str(preference_id),
            )
            .with_for_update()
        )
        payment = result.scalar_one_or_none()
        if payment:
            return payment

    if appointment_id:
        result = await db.execute(
            select(Payment)
            .where(
                Payment.store_id == store_id,
                Payment.appointment_id == str(appointment_id),
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    return None


async def _validate_payment_integrity(
    db: AsyncSession,
    *,
    store_id: str,
    payment: Payment,
    payload: dict[str, Any],
    configs: GatewayConfigs | None = None,
) -> None:
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    raw_metadata = data.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}

    expected_values = {
        "payment_id": payment.id,
        "appointment_id": payment.appointment_id,
        "store_id": store_id,
    }
    for key, expected in expected_values.items():
        received = str(metadata.get(key) or "").strip()
        if received and received != str(expected):
            raise RuntimeError(f"Mercado Pago devolvio metadata inconsistente: {key}")

    external_reference = str(
        data.get("external_reference") or payload.get("external_reference") or ""
    ).strip()
    if external_reference and external_reference != payment.appointment_id:
        raise RuntimeError("Mercado Pago devolvio una referencia externa inconsistente")

    received_amount = data.get("transaction_amount")
    if received_amount is not None and Decimal(str(received_amount)).quantize(
        Decimal("0.01")
    ) != Decimal(str(payment.amount)).quantize(Decimal("0.01")):
        raise RuntimeError("El importe acreditado no coincide con la seña esperada")

    currency = str(data.get("currency_id") or "").strip()
    if currency and currency != payment.currency:
        raise RuntimeError("La moneda acreditada no coincide con la esperada")

    preference_id = str(data.get("preference_id") or "").strip()
    if (
        preference_id
        and payment.preference_id
        and preference_id != payment.preference_id
    ):
        raise RuntimeError("La preferencia acreditada no coincide con la esperada")

    config = await resolve_gateway_config(db, store_id, configs)
    collector_id = str(data.get("collector_id") or "").strip()
    if config and config.oauth_user_id and collector_id:
        if collector_id != config.oauth_user_id:
            raise RuntimeError("El cobro pertenece a otra cuenta de Mercado Pago")


# Estados de un turno cuyo horario ya se solto: un pago que llega despues no
# lo revive (el horario pudo tomarlo otra persona). S-16, 2026-09-19.
_TURNO_LIBERADO = {
    AppointmentStatus.EXPIRED.value,
    AppointmentStatus.CANCELLED.value,
}


async def _publicar_aviso_de_cobro(
    db: AsyncSession, *, store_id: str, payment: Payment, event_type: str
) -> None:
    """Deja en el outbox un aviso de este cobro para el panel de la tienda."""
    result = await db.execute(
        select(Appointment, Service)
        .join(Service, Appointment.service_id == Service.id)
        .where(Appointment.id == payment.appointment_id)
    )
    row = result.first()
    appointment, service = row if row else (None, None)

    db.add(
        OutboxMessage(
            store_id=store_id,
            event_type=event_type,
            payload={
                "appointment_id": payment.appointment_id,
                "payment_id": payment.id,
                "amount": str(payment.amount),
                "client_name": appointment.client_name if appointment else None,
                "service_name": service.name if service else None,
            },
        )
    )


async def _notify_payment_approved(
    db: AsyncSession, *, store_id: str, payment: Payment, turno_liberado: bool
) -> None:
    """Deja en el outbox el aviso de seña acreditada para el panel de la tienda.

    Si el turno ya estaba liberado el evento es otro
    (``payment.received_on_released_appointment``): antes se publicaba
    ``payment.approved`` y el dueno leia "el turno quedo confirmado
    automaticamente" de un turno que no existia, y el cliente recibia el
    mail de "turno confirmado".
    """
    await _publicar_aviso_de_cobro(
        db,
        store_id=store_id,
        payment=payment,
        event_type=(
            NotificationType.PAYMENT_ON_RELEASED_APPOINTMENT.value
            if turno_liberado
            else NotificationType.PAYMENT_APPROVED.value
        ),
    )


async def _notify_payment_reversed(
    db: AsyncSession, *, store_id: str, payment: Payment, contracargo: bool
) -> None:
    """Avisa que la plata de un cobro ya acreditado se fue (AUD2-B2-04).

    Un contracargo deja el turno CONFIRMADO (criterio de
    ``sync_appointment_with_payment`` para ``refunded``, decision escrita del
    dueno) pero la plata ya no esta: sin este aviso el unico rastro era un
    numero en ``failed_webhooks``. El evento del contracargo es propio porque
    el del reembolso dice "la devolucion se hace desde Mercado Pago o en
    efectivo", que es justo lo que aca NO paso.
    """
    await _publicar_aviso_de_cobro(
        db,
        store_id=store_id,
        payment=payment,
        event_type=(
            NotificationType.PAYMENT_CHARGED_BACK.value
            if contracargo
            else NotificationType.PAYMENT_REFUNDED.value
        ),
    )


async def _avisar_al_dueno(
    db: AsyncSession,
    *,
    store_id: str,
    payment: Payment,
    appointment: Appointment | None,
    was_settled: bool,
    data: dict[str, Any],
) -> None:
    """Avisos al panel segun lo que el webhook hizo (o no pudo hacer) con la plata.

    Sale despues de sincronizar el turno: recien ahi se sabe si el pago
    confirmo el turno o llego tarde sobre uno ya liberado (S-16). El pago
    queda acreditado igual: la plata entro y hay que poder devolverla.
    """
    estado_remoto = str(data.get("status") or "").lower()
    if not was_settled and payment.status == PaymentStatus.APPROVED.value:
        await _notify_payment_approved(
            db,
            store_id=store_id,
            payment=payment,
            turno_liberado=appointment is None or appointment.status in _TURNO_LIBERADO,
        )
    # La plata que estaba asentada se fue: contracargo o reembolso hecho desde
    # Mercado Pago. El turno puede seguir confirmado, pero no en silencio.
    if was_settled and payment.status == PaymentStatus.REFUNDED.value:
        await _notify_payment_reversed(
            db,
            store_id=store_id,
            payment=payment,
            contracargo=estado_remoto == "charged_back",
        )
    # Disputa sobre un cobro ya acreditado (V-diff de AUD2-B2-04, 2026-09-20):
    # ``in_mediation`` mapea a ``pending`` y desde ``approved`` esa transicion
    # es ilegal, asi que el estado no cambia (decision: sin estado ni arista
    # nueva, regla 2). Pero Mercado Pago retiene la plata hasta resolverla y
    # antes eso no dejaba rastro: el inbox se sellaba y nadie se enteraba.
    if was_settled and estado_remoto == "in_mediation":
        await _publicar_aviso_de_cobro(
            db,
            store_id=store_id,
            payment=payment,
            event_type=NotificationType.PAYMENT_IN_MEDIATION.value,
        )


async def apply_mercadopago_webhook_payload(
    db: AsyncSession,
    *,
    store_id: str,
    payload: dict[str, Any],
    configs: GatewayConfigs | None = None,
) -> bool:
    payment = await find_payment_for_webhook(db, store_id, payload)
    payment_status = resolve_payment_status(payload)
    if not payment or not payment_status:
        return False

    await _validate_payment_integrity(
        db, store_id=store_id, payment=payment, payload=payload, configs=configs
    )

    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    external_payment_id = str(data.get("id") or payload.get("payment_id") or "").strip()
    was_settled = payment.status in {
        PaymentStatus.APPROVED.value,
        PaymentStatus.MANUAL_CONFIRMED.value,
    }
    aplicada = stamp_payment_from_status(
        payment,
        payment_status,
        payload=cast(dict[str, JsonValue], payload),
    )
    # El id del pago de MP se escribe DESPUES de la transicion y solo si la
    # entidad la acepto (AUD2-B2-05, 2026-09-20). Antes se escribia primero:
    # con un reintento del cliente (pago A aprobado, pago B rechazado sobre la
    # misma preferencia) el webhook de B se descartaba por el grafo pero ya
    # habia dejado el id de B, contra un raw_payload que seguia siendo el de
    # A. Un cobro sin id lo toma igual: es la unica trazabilidad que hay.
    if external_payment_id and (aplicada or not payment.external_payment_id):
        payment.external_payment_id = external_payment_id
    appointment_result = await db.execute(
        select(Appointment)
        .where(
            Appointment.id == payment.appointment_id, Appointment.store_id == store_id
        )
        .with_for_update()
    )
    appointment = appointment_result.scalar_one_or_none()
    if appointment:
        appointment_start = appointment.starts_at
        if appointment_start.tzinfo is None:
            appointment_start = appointment_start.replace(tzinfo=timezone.utc)
        if (
            payment_status == PaymentStatus.APPROVED.value
            and appointment.status == AppointmentStatus.PENDING_PAYMENT.value
            and appointment_start <= datetime.now(timezone.utc)
        ):
            appointment.apply_status_transition(AppointmentStatus.EXPIRED)
        sync_appointment_with_payment(appointment, payment.status)
    await _avisar_al_dueno(
        db,
        store_id=store_id,
        payment=payment,
        appointment=appointment,
        was_settled=was_settled,
        data=data,
    )
    return True
