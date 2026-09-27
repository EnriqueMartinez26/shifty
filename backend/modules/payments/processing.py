from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.observability import report_exception
from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import NotificationType
from modules.payments.links import (
    adopt_retired_link,
    classify_payment_link,
    pays_retired_link,
)
from modules.payments.model import (
    OutboxMessage,
    can_apply_payment_status,
    appointment_id_from_reference,
    external_reference_for,
    Payment,
    PaymentLinkHistory,
    PaymentStatus,
)
from modules.payments.minimization import minimize_payment_payload
from modules.services.model import Service
from modules.payments.service import (
    RELEASED_APPOINTMENT_STATUSES,
    GatewayConfigs,
    PersistRefresh,
    expire_live_charge,
    fetch_mercadopago_payment,
    resolve_gateway_config,
    stamp_payment_from_status,
    sync_appointment_with_payment,
)


logger = structlog.get_logger()


class PaymentOnReplacedLink(RuntimeError):
    """Evento de Sentry: entro plata por un link que el cobro ya no usa."""


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
    """El cobro al que se refiere el webhook, SIN lock.

    Solo dice de que turno es: el lock lo toma ``apply_mercadopago_webhook_payload``
    en el orden unico turno -> pago (F1-18, decision 23 del plan). Antes esta
    busqueda lockeaba el pago primero y el panel y el job de vencimiento lockean
    el turno primero: dos ordenes opuestos sobre las mismas filas.
    """
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    raw_metadata = data.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}

    referencia = payload.get("external_reference") or data.get("external_reference")
    appointment_id = (
        metadata.get("appointment_id")
        or payload.get("appointment_id")
        # ``<turno>:<link_ref>`` desde perf/f4-pay; el turno solo, antes.
        or (appointment_id_from_reference(str(referencia)) if referencia else None)
    )
    preference_id = data.get("preference_id") or payload.get("preference_id")
    external_payment_id = (
        str(data.get("id") or payload.get("payment_id") or "").strip() or None
    )

    if external_payment_id:
        result = await db.execute(
            select(Payment).where(
                Payment.store_id == store_id,
                Payment.external_payment_id == external_payment_id,
            )
        )
        payment = result.scalar_one_or_none()
        if payment:
            return payment

    if preference_id:
        result = await db.execute(
            select(Payment).where(
                Payment.store_id == store_id,
                Payment.preference_id == str(preference_id),
            )
        )
        payment = result.scalar_one_or_none()
        if payment:
            return payment

    if appointment_id:
        result = await db.execute(
            select(Payment).where(
                Payment.store_id == store_id,
                Payment.appointment_id == str(appointment_id),
            )
        )
        return result.scalar_one_or_none()

    return None


async def _validate_payment_identity(
    db: AsyncSession,
    *,
    store_id: str,
    payment: Payment,
    payload: dict[str, Any],
    configs: GatewayConfigs | None = None,
) -> None:
    """El pago es de ESTE cobro: metadata, turno de la referencia, moneda y
    cuenta de MP.

    Corre ANTES de clasificar el link del pago (revision de perf/f4-pay,
    2026-09-25): un payload que no es de este cobro se rechaza por integridad
    y nunca dispara Sentry ni un aviso al dueno como "pago sobre un link
    reemplazado".
    """
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

    external_reference = _referencia_del_pago(payload)
    if external_reference and (
        appointment_id_from_reference(external_reference) != payment.appointment_id
    ):
        raise RuntimeError("Mercado Pago devolvio una referencia externa inconsistente")

    currency = str(data.get("currency_id") or "").strip()
    if currency and currency != payment.currency:
        raise RuntimeError("La moneda acreditada no coincide con la esperada")

    config = await resolve_gateway_config(db, store_id, configs)
    collector_id = str(data.get("collector_id") or "").strip()
    if config and config.oauth_user_id and collector_id:
        if collector_id != config.oauth_user_id:
            raise RuntimeError("El cobro pertenece a otra cuenta de Mercado Pago")


def _referencia_del_pago(payload: dict[str, Any]) -> str:
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    return str(
        data.get("external_reference") or payload.get("external_reference") or ""
    ).strip()


@dataclass(frozen=True)
class _LinkEsperado:
    """Contra que link se valida un pago: el vigente del cobro o uno de su
    historial que se va a adoptar."""

    link_ref: str | None
    referencia: str
    importe: Decimal
    preferencia: str | None

    @classmethod
    def vigente(cls, payment: Payment) -> _LinkEsperado:
        return cls(
            link_ref=payment.link_ref,
            referencia=payment.current_external_reference,
            importe=payment.amount,
            preferencia=payment.preference_id,
        )

    @classmethod
    def retirado(cls, payment: Payment, fila: PaymentLinkHistory) -> _LinkEsperado:
        return cls(
            link_ref=fila.link_ref,
            referencia=external_reference_for(payment.appointment_id, fila.link_ref),
            importe=fila.amount,
            preferencia=fila.preference_id,
        )


def _validate_payment_link(
    payment: Payment, payload: dict[str, Any], esperado: _LinkEsperado | None = None
) -> None:
    """El pago es del link esperado (el VIGENTE si no se dice otro) y por su
    importe.

    La referencia de un link es ``<turno>:<link_ref>`` (el turno solo si el
    link es de antes de la columna): un pago de un link reemplazado no se
    aplica aunque MP no mande ``preference_id``, que el pago no trae
    (revision de perf/f4-pay, 2026-09-25). ``esperado``: el link retirado que
    se va a adoptar, validado ANTES de tocar el cobro (revision #2).
    """
    link = esperado or _LinkEsperado.vigente(payment)
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    external_reference = _referencia_del_pago(payload)
    # Con nonce, un pago sin referencia no dice de que link es: no se aplica
    # (antes pasaba, fail-open; revision de perf/f4-pay, 2026-09-25). Sin
    # nonce (link de antes de la columna) se tolera como siempre.
    if link.link_ref and not external_reference:
        raise RuntimeError("Mercado Pago no devolvio la referencia externa del link")
    if external_reference and external_reference != link.referencia:
        raise RuntimeError("Mercado Pago devolvio una referencia externa inconsistente")

    received_amount = data.get("transaction_amount")
    if received_amount is not None and Decimal(str(received_amount)).quantize(
        Decimal("0.01")
    ) != Decimal(str(link.importe)).quantize(Decimal("0.01")):
        raise RuntimeError("El importe acreditado no coincide con la seña esperada")

    preference_id = str(data.get("preference_id") or "").strip()
    if preference_id and link.preferencia and preference_id != link.preferencia:
        raise RuntimeError("La preferencia acreditada no coincide con la esperada")


# Estados de un turno cuyo horario ya se solto: un pago que llega despues no
# lo revive (el horario pudo tomarlo otra persona). S-16, 2026-09-19. Misma
# fuente que el link del panel y la confirmacion manual.
_TURNO_LIBERADO = RELEASED_APPOINTMENT_STATUSES


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


async def _disputa_ya_avisada(
    db: AsyncSession, *, store_id: str, payment: Payment
) -> bool:
    """Si ya hay un aviso de disputa publicado para este cobro (AUD2-POST-10).

    Mercado Pago reenvia el webhook en cada actualizacion de la disputa, cada
    vez con un ``event_id`` nuevo: la idempotencia del inbox no lo frena y el
    estado del cobro no cambia (``approved`` -> ``pending`` es ilegal), asi
    que sin esta consulta cada reenvio era otro aviso identico al dueno.
    """
    result = await db.execute(
        select(OutboxMessage.id)
        .where(
            OutboxMessage.store_id == store_id,
            OutboxMessage.event_type == NotificationType.PAYMENT_IN_MEDIATION.value,
            OutboxMessage.payload["payment_id"].as_string() == payment.id,
        )
        .limit(1)
    )
    return result.first() is not None


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
    if (
        was_settled
        and estado_remoto == "in_mediation"
        and not await _disputa_ya_avisada(db, store_id=store_id, payment=payment)
    ):
        await _publicar_aviso_de_cobro(
            db,
            store_id=store_id,
            payment=payment,
            event_type=NotificationType.PAYMENT_IN_MEDIATION.value,
        )


def _sync_appointment(
    db: AsyncSession, appointment: Appointment, payment: Payment, payment_status: str
) -> None:
    """Lleva el turno (ya lockeado) al estado que corresponde al pago.

    Un ``approved`` que llega con el turno ``pending_payment`` ya empezado lo
    vence en vez de confirmarlo. Si el pago solto el turno (un rechazo pasa
    un ``pending_payment`` a ``expired``), su cobro vivo se vence con el
    camino compartido, turno y pago ya lockeados (revision de perf/f4-pay,
    2026-09-25). Antes quedaba ``rejected`` con el link vivo en MP.
    """
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
    if appointment.status in RELEASED_APPOINTMENT_STATUSES:
        expire_live_charge(db, payment, reason="appointment_released_by_payment")


async def _resolver_link(
    db: AsyncSession,
    *,
    store_id: str,
    payment: Payment,
    payload: dict[str, Any],
    payment_status: str,
) -> bool | None:
    """De que link del cobro es el pago y que se hace (revision de perf/f4-pay).

    None: sigue el camino normal (link vigente, o un link RETIRADO del cobro
    que se adopta). True/False: ya resuelto, con eso responde el webhook.

    Un evento no aprobado (``in_process``, ``rejected``, ``refunded``,
    ``charged_back``) de un link que no es el vigente es un no-op PROCESADO
    (True: el inbox lo cierra) con un log de info. Revision de
    7abb9b4..e5579b6 (#6): devolver False lo dejaba reintentar 10 veces hasta
    quedar como dead letter y disparar la alerta critica
    ``dead_letter_webhooks`` sin plata acreditada que revisar.

    Un ``approved`` de un link retirado (webhook tardio o reentregado, o un
    pago hecho antes de que MP venciera ese link) se aplica si el cobro todavia
    no esta acreditado y el pago es por el importe y la moneda de ESE link:
    el cobro adopta ese link y el vigente se vence (``adopt_retired_link``).
    Si el cobro ya esta acreditado (o devuelto) es un pago duplicado; si el
    importe no es el de ese link, o el link no es conocido, va al camino de
    alerta. La identidad ya se valido: esto nunca corre con un payload ajeno.
    """
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    link = await classify_payment_link(db, payment, data, _referencia_del_pago(payload))
    if link.tipo == "vigente":
        return None
    if payment_status != PaymentStatus.APPROVED.value:
        logger.info(
            "payment_on_replaced_link_ignored",
            store_id=store_id,
            payment_id=payment.id,
            status=payment_status,
        )
        return True
    abierto = not payment.is_accredited and can_apply_payment_status(
        payment.status, PaymentStatus.APPROVED.value
    )
    if abierto and link.retirado is not None and pays_retired_link(link.retirado, data):
        # Todas las verificaciones ANTES de tocar el cobro (revision de
        # e5579b6..3b977a9, #2): una que fallara despues de adoptar dejaba
        # la adopcion a medias, y el webhook HTTP commitea tras
        # ``register_failure``.
        _validate_payment_link(
            payment, payload, _LinkEsperado.retirado(payment, link.retirado)
        )
        adopt_retired_link(db, payment, link.retirado)
        return None
    await _pago_en_link_reemplazado(
        db, store_id=store_id, payment=payment, payload=payload, duplicado=not abierto
    )
    return False


async def _pago_en_link_reemplazado(
    db: AsyncSession,
    *,
    store_id: str,
    payment: Payment,
    payload: dict[str, Any],
    duplicado: bool,
) -> None:
    """No se aplica, pero la plata acreditada nunca queda en silencio.

    Revision de perf/f4-pay (2026-09-25): aplicar un ``approved`` de un link
    reemplazado dejaria vivo el link vigente (el cliente pagaria dos veces).
    Si entro plata: warning con ids (sin datos personales), evento a Sentry y
    un aviso al dueno, los tres UNA vez por pago de MP (revision de
    7abb9b4..e5579b6, #6: antes el warning y Sentry salian en cada reintento
    del inbox). El webhook queda sin aplicar: el inbox lo reintenta hasta
    agotar y queda como dead letter, visible en ``/ops/slo``. ``duplicado``:
    el cobro ya estaba acreditado (o devuelto): el aviso pide devolver el pago.
    """
    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    mp_payment_id = str(data.get("id") or payload.get("payment_id") or "").strip()
    clave = _clave_del_aviso(mp_payment_id, payload)
    if clave is not None and await _aviso_publicado(db, store_id, clave):
        return
    contexto = {
        "store_id": store_id,
        "payment_id": payment.id,
        "mp_payment_id": mp_payment_id,
        "duplicado": duplicado,
    }
    logger.warning("payment_on_replaced_link", **contexto)
    report_exception(
        PaymentOnReplacedLink("pago sobre un link reemplazado"), **contexto
    )
    db.add(
        OutboxMessage(
            store_id=store_id,
            event_type=NotificationType.PAYMENT_ON_REPLACED_LINK.value,
            payload={
                "appointment_id": payment.appointment_id,
                "payment_id": payment.id,
                "mp_payment_id": mp_payment_id,
                "amount": str(data.get("transaction_amount") or ""),
                "duplicado": duplicado,
                "aviso": clave,
            },
        )
    )


def _clave_del_aviso(mp_payment_id: str, payload: dict[str, Any]) -> str | None:
    """Clave de deduplicacion del aviso de un pago en un link reemplazado.

    Por pago de MP; sin id de pago, por evento (el id de la notificacion de
    MP, el mismo que identifica la fila del inbox): la cadena vacia no puede
    ser una clave, con ella el primer aviso tapaba todos los de la tienda.
    Sin ninguno de los dos no se deduplica (None): se avisa cada vez.
    """
    if mp_payment_id:
        return f"pago:{mp_payment_id}"
    evento = str(payload.get("id") or payload.get("resource") or "").strip()
    return f"evento:{evento}" if evento else None


async def _aviso_publicado(db: AsyncSession, store_id: str, clave: str) -> bool:
    fila = await db.execute(
        select(OutboxMessage.id)
        .where(
            OutboxMessage.store_id == store_id,
            OutboxMessage.event_type == NotificationType.PAYMENT_ON_REPLACED_LINK.value,
            OutboxMessage.payload["aviso"].as_string() == clave,
        )
        .limit(1)
    )
    return fila.first() is not None


async def _lock_turno_y_pago(
    db: AsyncSession, store_id: str, encontrado: Payment
) -> tuple[Appointment | None, Payment | None]:
    """Turno y pago del webhook, lockeados en el orden unico TURNO -> PAGO.

    F1-18 (decision 23 del plan): el mismo orden que liberar desde el panel y
    el job de vencimiento. Se releen bajo su lock (populate_existing): entre
    la busqueda sin lock y el lock pudieron cambiar, y todo lo que sigue
    decide sobre la version lockeada.
    """
    appointment = (
        await db.execute(
            select(Appointment)
            .where(
                Appointment.id == encontrado.appointment_id,
                Appointment.store_id == store_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    payment = (
        await db.execute(
            select(Payment)
            .where(Payment.id == encontrado.id, Payment.store_id == store_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return appointment, payment


def _stamp_payment(
    payment: Payment,
    payment_status: str,
    payload: dict[str, Any],
    data: dict[str, Any],
) -> None:
    """Aplica el estado remoto por el grafo y anota el id del pago de MP.

    El id se escribe DESPUES de la transicion y solo si la entidad la acepto
    (AUD2-B2-05, 2026-09-20). Antes se escribia primero: con un reintento del
    cliente (pago A aprobado, pago B rechazado sobre la misma preferencia) el
    webhook de B se descartaba por el grafo pero ya habia dejado el id de B,
    contra un raw_payload que seguia siendo el de A. Un cobro sin id lo toma
    igual: es la unica trazabilidad que hay.
    """
    external_payment_id = str(data.get("id") or payload.get("payment_id") or "").strip()
    # Se persiste la lista blanca, no el recurso de MP (L3-01): la
    # conciliacion trae email, identificacion y tarjeta del pagador.
    aplicada = stamp_payment_from_status(
        payment, payment_status, payload=minimize_payment_payload(payload)
    )
    if external_payment_id and (aplicada or not payment.external_payment_id):
        payment.external_payment_id = external_payment_id


async def apply_mercadopago_webhook_payload(
    db: AsyncSession,
    *,
    store_id: str,
    payload: dict[str, Any],
    configs: GatewayConfigs | None = None,
) -> bool:
    encontrado = await find_payment_for_webhook(db, store_id, payload)
    payment_status = resolve_payment_status(payload)
    if not encontrado or not payment_status:
        return False

    appointment, payment = await _lock_turno_y_pago(db, store_id, encontrado)
    if payment is None:
        return False
    # Identidad primero: lo que no es de este cobro no llega a clasificarse.
    await _validate_payment_identity(
        db, store_id=store_id, payment=payment, payload=payload, configs=configs
    )
    resuelto = await _resolver_link(
        db,
        store_id=store_id,
        payment=payment,
        payload=payload,
        payment_status=payment_status,
    )
    if resuelto is not None:
        return resuelto

    _validate_payment_link(payment, payload)

    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    was_settled = payment.is_accredited
    _stamp_payment(payment, payment_status, payload, data)
    if appointment:
        _sync_appointment(db, appointment, payment, payment_status)
    await _avisar_al_dueno(
        db,
        store_id=store_id,
        payment=payment,
        appointment=appointment,
        was_settled=was_settled,
        data=data,
    )
    return True
