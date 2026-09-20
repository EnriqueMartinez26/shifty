from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

import structlog
from redis.exceptions import RedisError
from sqlalchemy import Select, or_, select, text
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from core.availability_cache import invalidate_availability
from core.database import _apply_tenant_context
from core.redis import get_redis
from core.utils import ensure_utc_aware
from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import Notification, NotificationType
from modules.notifications.tasks import (
    build_client_details,
    send_waitlist_offer_email,
    format_local_datetime,
    send_cancellation_email,
    send_confirmation_email,
    send_store_notification_email,
)
from modules.payments.model import (
    JsonValue,
    OutboxMessage,
    Payment,
    PaymentGatewayConfig,
    PaymentStatus,
    WebhookInbox,
)
from modules.payments.processing import (
    apply_mercadopago_webhook_payload,
    enrich_mercadopago_webhook_payload,
)
from modules.users.model import User, UserRole
from modules.waitlist.events import EVENT_SLOT_RELEASED, publish_slot_released
from modules.waitlist.offers import ReleasedSlot, offer_released_slot
from modules.payments.service import (
    EVENT_PREFERENCE_EXPIRE,
    GatewayConfigs,
    PersistRefresh,
    expire_mercadopago_preference,
    fetch_mercadopago_payment,
    load_gateway_configs,
    stamp_payment_from_status,
    search_mercadopago_payments,
)

# Ventana hacia atras que revisa la conciliacion. Mas alla de esto un pago
# pendiente ya se considera abandonado.
RECONCILIATION_LOOKBACK_DAYS = 30

logger = structlog.get_logger()

# Vencimiento del link de MP en dos fases (B1-04). El lote del outbox RECLAMA
# el evento (processed_at provisorio + este marcador en ``error``) y commitea;
# la llamada a MP corre despues, sin lock ni transaccion abierta; el resultado
# se anota en una transaccion nueva (exito: se limpia el marcador; fallo:
# vuelve a la cola con register_failure y su techo de B2-12). Si el worker
# muere entre el reclamo y el resultado, el reclamo vence a los
# PREFERENCE_EXPIRE_LEASE y la corrida siguiente lo retoma: un crash solo
# demora el reintento, no deja el link vivo. El lease tiene que ser mayor que
# lo que puede tardar una corrida (timeout HTTP de MP por evento del lote).
PREFERENCE_EXPIRE_CLAIM = "claimed:" + EVENT_PREFERENCE_EXPIRE
PREFERENCE_EXPIRE_LEASE = timedelta(minutes=10)
# Peor caso de un reclamo: el timeout de httpx de cada request a MP
# (``_perform_mercadopago_request`` y el token OAuth usan 20 s) por las tres
# requests que puede hacer un vencimiento (PUT con 401, refresh OAuth, PUT de
# nuevo). El tope de reclamos por corrida hace que el peor caso de la corrida
# entera, mas un margen para leer la config y anotar resultados, entre en el
# lease: ``MAX_CLAIMS * WORST_CASE_PER_CLAIM + MARGIN < LEASE`` (lo verifica
# test_el_peor_caso_de_una_corrida_entra_en_el_lease). Lo que no entra en una
# corrida espera a la siguiente, un minuto despues.
MP_REQUEST_TIMEOUT = timedelta(seconds=20.0)
PREFERENCE_EXPIRE_WORST_CASE_PER_CLAIM = 3 * MP_REQUEST_TIMEOUT
PREFERENCE_EXPIRE_MARGIN = timedelta(minutes=1)
PREFERENCE_EXPIRE_MAX_CLAIMS = 8


@dataclass(frozen=True)
class _PreferenceExpireClaim:
    message_id: str
    store_id: str
    preference_id: str
    # Instante del reclamo: si al anotar el resultado ``processed_at`` ya no
    # es este, otra corrida lo retomo y el resultado no es de esta.
    claimed_at: datetime


# Mail listo para mandar DESPUES del commit del lote (regla 5). Adentro de la
# transaccion quedaria bajo el FOR UPDATE SKIP LOCKED y, si Celery mata la
# tarea antes del commit, la corrida siguiente reenviaria lo ya enviado. Es la
# misma funcion de envio de siempre con sus argumentos ya fijados: conserva
# is_deliverable_email y el best-effort de cada camino.
PendingEmail = Callable[[], Awaitable[object]]


def _contexto_del_mail(message: OutboxMessage) -> dict[str, str | None]:
    """De que tienda y turno es un mail del outbox, para el log si no sale.

    Solo identificadores: ni email ni nombre del cliente (S-04, 2026-09-18;
    se habian perdido al sacar los envios de la transaccion en B2-01).
    """
    payload = message.payload if isinstance(message.payload, dict) else {}
    turno = payload.get("appointment_id") or payload.get("public_id")
    return {
        "store_id": message.store_id,
        "appointment_id": str(turno) if turno else None,
        "event_type": message.event_type,
    }


async def process_outbox_batch(
    db: AsyncSession,
    *,
    limit: int = 100,
    store_id: str | None = None,
) -> dict[str, int]:
    filters: list[ColumnElement[bool]] = [
        OutboxMessage.processed_at.is_(None),
        OutboxMessage.is_active.is_(True),
        # Los vencimientos de links de MP tienen su propio paso (abajo): asi
        # los mails de este lote no esperan a Mercado Pago (B1-04). Es un
        # predicado mas sobre las filas del indice parcial ix_outbox_pending.
        OutboxMessage.event_type != EVENT_PREFERENCE_EXPIRE,
    ]
    if store_id:
        filters.append(OutboxMessage.store_id == store_id)

    result = await db.execute(
        select(OutboxMessage)
        .where(*filters)
        .order_by(OutboxMessage.created_at.asc())
        .limit(limit)
        # Dos corridas solapadas (beat cada minuto) no deben tomar el mismo
        # mensaje: sin esto se duplicaban notificaciones y mails (regla 8).
        .with_for_update(skip_locked=True)
    )
    messages = list(result.scalars().all())
    now = datetime.now(timezone.utc)
    processed = 0
    failed = 0
    # Ningun mail sale dentro del lote: el cuerpo del for solo persiste y
    # acumula; todo se despacha despues del unico commit (2026-09-16, B2-01).
    mails_pendientes: list[tuple[PendingEmail, dict[str, str | None]]] = []

    for message in messages:
        contexto = _contexto_del_mail(message)
        try:
            if message.event_type == EVENT_SLOT_RELEASED and message.store_id:
                # Lista de espera: aviso al dueno y oferta a una persona por vez.
                oferta = await offer_released_slot(
                    db,
                    ReleasedSlot.from_payload(
                        message.store_id, dict(message.payload or {})
                    ),
                    now=now,
                )
                if oferta.pending_email:
                    mails_pendientes.append(
                        (
                            partial(
                                send_waitlist_offer_email,
                                email=oferta.pending_email.email,
                                details=oferta.pending_email.details,
                            ),
                            contexto,
                        )
                    )
            elif message.event_type == "appointment.cancelled_by_block":
                # Aviso al cliente (no al dueno, que fue quien bloqueo).
                payload = dict(message.payload or {})
                mails_pendientes.append(
                    (
                        partial(
                            send_cancellation_email,
                            email=str(payload.get("client_email") or "") or None,
                            details=payload,
                        ),
                        contexto,
                    )
                )
            else:
                notification = _build_store_notification(message)
                if notification is not None:
                    # La notificacion in-app es la fuente durable; el mail es
                    # un efecto secundario que sale despues del commit.
                    db.add(notification)
                    mails_pendientes.extend(
                        (mail, contexto)
                        for mail in await _store_owner_mails(db, notification)
                    )
                    if message.event_type == NotificationType.PAYMENT_APPROVED.value:
                        # La sena acreditada confirma el turno: el cliente
                        # tambien se entera.
                        confirmacion = await _client_confirmation_mail(
                            db, notification.appointment_id
                        )
                        if confirmacion is not None:
                            mails_pendientes.append((confirmacion, contexto))
            message.processed_at = now
            message.error = None
            processed += 1
        except Exception as exc:
            message.register_failure(str(exc))
            failed += 1

    await db.commit()
    # Recien ahora, con la transaccion cerrada y processed_at persistido, se
    # mandan los mails. Un SMTP caido no revierte nada, no marca el evento
    # como fallido ni duplica envios.
    for enviar, contexto in mails_pendientes:
        try:
            await enviar()
        except Exception as exc:
            logger.warning(
                "outbox_email_skipped", error_type=type(exc).__name__, **contexto
            )
    # Despues de los mails, el paso propio de los vencimientos de MP.
    vencimientos = await _claim_and_expire_preferences(db, store_id=store_id)
    return {
        "processed": processed + vencimientos["processed"],
        "failed": failed + vencimientos["failed"],
        "inspected": len(messages) + vencimientos["inspected"],
    }


async def _claim_and_expire_preferences(
    db: AsyncSession, *, store_id: str | None = None
) -> dict[str, int]:
    """Vence los links de MP de ``payment.preference.expire`` (B1-04).

    Paso propio, separado del lote comun para que los mails de ese lote no
    esperen a Mercado Pago. Reclamo y llamadas quedan pegados, asi el lease
    se cuenta desde justo antes de llamar:

    1. Toma con ``FOR UPDATE SKIP LOCKED`` hasta PREFERENCE_EXPIRE_MAX_CLAIMS
       eventos: primero los reclamos con lease vencido (worker muerto), despues
       los pendientes. Dos consultas: los pendientes usan el indice parcial
       ``ix_outbox_pending``; un ``OR`` con los reclamos lo rompia.
    2. Marca el reclamo y commitea.
    3. Llama a MP sin lock ni transaccion abierta.
    4. Anota el resultado en una transaccion nueva, releyendo cada fila.
    """
    now = datetime.now(timezone.utc)
    alcance: list[ColumnElement[bool]] = [
        OutboxMessage.event_type == EVENT_PREFERENCE_EXPIRE,
        OutboxMessage.is_active.is_(True),
    ]
    if store_id:
        alcance.append(OutboxMessage.store_id == store_id)
    retomados = list(
        (
            await db.execute(
                select(OutboxMessage)
                .where(
                    *alcance,
                    OutboxMessage.error == PREFERENCE_EXPIRE_CLAIM,
                    OutboxMessage.processed_at < now - PREFERENCE_EXPIRE_LEASE,
                )
                .order_by(OutboxMessage.processed_at.asc())
                .limit(PREFERENCE_EXPIRE_MAX_CLAIMS)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    pendientes: list[OutboxMessage] = []
    if len(retomados) < PREFERENCE_EXPIRE_MAX_CLAIMS:
        pendientes = list(
            (
                await db.execute(
                    select(OutboxMessage)
                    .where(*alcance, OutboxMessage.processed_at.is_(None))
                    .order_by(OutboxMessage.created_at.asc())
                    .limit(PREFERENCE_EXPIRE_MAX_CLAIMS - len(retomados))
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
    mensajes = retomados + pendientes
    if not mensajes:
        await db.commit()
        return {"processed": 0, "failed": 0, "inspected": 0}

    reclamos: list[_PreferenceExpireClaim] = []
    procesados = 0
    abandonados = 0
    for message in mensajes:
        reclamo = _claim_preference_expire(message, now)
        if reclamo is not None:
            reclamos.append(reclamo)
        elif message.processed_at is not None:
            # Agoto los intentos con reclamos vencidos: queda con error.
            abandonados += 1
        else:
            # Sin preference_id no hay link que vencer.
            message.processed_at = now
            message.error = None
            procesados += 1
    await db.commit()

    vencidos, fallidos = await _expire_claimed_preferences(db, reclamos)
    return {
        "processed": procesados + vencidos,
        "failed": abandonados + fallidos,
        "inspected": len(mensajes),
    }


def _claim_preference_expire(
    message: OutboxMessage, now: datetime
) -> _PreferenceExpireClaim | None:
    """Marca el reclamo del vencimiento, sin llamar a nadie.

    ``processed_at`` provisorio saca el evento de las otras corridas y el
    marcador en ``error`` lo distingue de uno procesado de verdad (el lease
    lo devuelve si el worker muere). Un reclamo vencido cuenta como intento
    fallido: con el techo de B2-12 alcanzado se abandona (devuelve None y
    queda procesado con error). Sin datos para llamar a MP devuelve None y
    no toca nada: no hay link que vencer.
    """
    payload = message.payload if isinstance(message.payload, dict) else {}
    preference_id = str(payload.get("preference_id") or "")
    if not preference_id or not message.store_id:
        return None
    if message.error == PREFERENCE_EXPIRE_CLAIM:
        message.processed_at = None
        message.register_failure("reclamo vencido sin resultado")
        if message.processed_at is not None:
            return None
    message.processed_at = now
    message.error = PREFERENCE_EXPIRE_CLAIM
    return _PreferenceExpireClaim(
        message_id=message.id,
        store_id=message.store_id,
        preference_id=preference_id,
        claimed_at=now,
    )


async def _expire_claimed_preferences(
    db: AsyncSession, reclamos: list[_PreferenceExpireClaim]
) -> tuple[int, int]:
    """Vence los links ya reclamados (y commiteados) y anota el resultado.

    La config del gateway se lee antes y la transaccion de lectura se cierra
    ANTES del HTTP (mismo patron que ``_expire_unpaid_appointments``, S-02):
    ninguna llamada a MP corre con lock ni con transaccion abierta. El
    resultado se escribe en una transaccion nueva. Devuelve (vencidos,
    fallidos).
    """
    if not reclamos:
        return 0, 0
    configs = await load_gateway_configs(db, (r.store_id for r in reclamos))
    await AsyncSession.commit(db)
    errores: dict[str, tuple[_PreferenceExpireClaim, str | None]] = {}
    for reclamo in reclamos:
        try:
            await expire_mercadopago_preference(
                db,
                store_id=reclamo.store_id,
                preference_id=reclamo.preference_id,
                configs=configs,
                persist_refresh=partial(_persist_refresh_in_short_transaction, db),
            )
            errores[reclamo.message_id] = (reclamo, None)
        except Exception as exc:
            logger.warning(
                "preference_expire_failed",
                store_id=reclamo.store_id,
                message_id=reclamo.message_id,
                error_type=type(exc).__name__,
            )
            errores[reclamo.message_id] = (reclamo, f"{type(exc).__name__}: {exc}")

    await _apply_tenant_context(db)
    vencidos = 0
    fallidos = 0
    for message_id, (reclamo, error) in errores.items():
        # Se relee DE LA BASE y con lock: ``db.get`` devolvia la instancia en
        # memoria (expire_on_commit=False) y nunca veia que otra corrida lo
        # habia retomado (revision de B1-04).
        message = (
            await db.execute(
                select(OutboxMessage)
                .where(OutboxMessage.id == message_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if (
            message is None
            or message.error != PREFERENCE_EXPIRE_CLAIM
            or message.processed_at is None
            or ensure_utc_aware(message.processed_at) != reclamo.claimed_at
        ):
            continue  # ya no es nuestro reclamo
        if error is None:
            message.error = None
            vencidos += 1
        else:
            message.processed_at = None
            message.register_failure(error)
            fallidos += 1
    await db.commit()
    return vencidos, fallidos


def _build_store_notification(message: OutboxMessage) -> Notification | None:
    """Traduce un evento del outbox en una notificacion para el panel de la tienda.

    Un evento sin rama aca se consume sin aviso. Desde B2-17 (2026-09-19) todo
    evento de pago que se publica tiene su rama: los que no le servian a nadie
    (payment.manual_confirmed, payment.preference.created) dejaron de
    publicarse.
    """
    if not message.store_id:
        return None

    payload = message.payload if isinstance(message.payload, dict) else {}
    appointment_id = payload.get("appointment_id")
    client_name = str(payload.get("client_name") or "Un cliente")
    service_name = str(payload.get("service_name") or "un servicio")

    if message.event_type == NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value:
        return Notification(
            store_id=message.store_id,
            type=message.event_type,
            title="Turno pendiente de confirmar",
            body=(
                f"{client_name} reservo {service_name} y va a coordinar el pago. "
                "Confirmalo cuando recibas la transferencia."
            ),
            appointment_id=str(appointment_id) if appointment_id else None,
        )

    if message.event_type == NotificationType.APPOINTMENT_CANCELLED_BY_CLIENT.value:
        cuando = payload.get("starts_at")
        fecha, hora = format_local_datetime(cuando) if cuando else ("", "")
        # El motivo del cliente va al cuerpo, nunca al titulo (que es el
        # asunto del mail), y en una sola linea, sin CR/LF (B1-23).
        motivo = " ".join(str(payload.get("reason") or "").split())
        return Notification(
            store_id=message.store_id,
            type=message.event_type,
            title="Un cliente cancelo su turno",
            body=(
                f"{client_name} cancelo {service_name}"
                + (f" del {fecha} a las {hora}" if fecha else "")
                + ". El horario volvio a estar disponible."
                + (f" Motivo: {motivo}" if motivo else "")
            ),
            appointment_id=str(appointment_id) if appointment_id else None,
        )

    if message.event_type == NotificationType.SUBSCRIPTION_EXPIRING.value:
        dias = payload.get("days_left")
        plan = str(payload.get("plan_name") or "tu plan")
        cuando = (
            "hoy"
            if dias == 0
            else f"en {dias} dia" + ("s" if isinstance(dias, int) and dias != 1 else "")
        )
        return Notification(
            store_id=message.store_id,
            type=message.event_type,
            title="Tu suscripcion vence pronto",
            body=(
                f"{plan} vence {cuando}. Renovala para que tu pagina de reservas "
                "siga funcionando."
            ),
        )

    if message.event_type == NotificationType.PAYMENT_APPROVED.value:
        amount = payload.get("amount")
        amount_label = f" de ${amount}" if amount else ""
        return Notification(
            store_id=message.store_id,
            type=message.event_type,
            title="Seña acreditada",
            body=(
                f"{client_name} pago la seña{amount_label} de {service_name}. "
                "El turno quedo confirmado automaticamente."
            ),
            appointment_id=str(appointment_id) if appointment_id else None,
        )

    if message.event_type == NotificationType.PAYMENT_REFUNDED.value:
        amount = payload.get("amount")
        amount_label = f" de ${amount}" if amount else ""
        return Notification(
            store_id=message.store_id,
            type=message.event_type,
            title="Reembolso registrado",
            body=(
                f"Se registro un reembolso{amount_label}. Shifty no mueve la plata: "
                "la devolucion se hace desde Mercado Pago o en efectivo."
            ),
            appointment_id=str(appointment_id) if appointment_id else None,
        )

    if message.event_type == NotificationType.PAYMENT_CHARGED_BACK.value:
        # AUD2-B2-04: el contracargo no es un reembolso que hizo la tienda.
        amount = payload.get("amount")
        amount_label = f" de ${amount}" if amount else ""
        return Notification(
            store_id=message.store_id,
            type=message.event_type,
            title="Contracargo en Mercado Pago",
            body=(
                f"Mercado Pago devolvio el pago{amount_label} de {client_name} "
                f"por {service_name}: esa plata ya no esta en tu cuenta. El "
                "turno sigue confirmado; si no lo vas a atender, cancelalo."
            ),
            appointment_id=str(appointment_id) if appointment_id else None,
        )

    if message.event_type == NotificationType.PAYMENT_ON_RELEASED_APPOINTMENT.value:
        # S-16: pago acreditado de un turno que ya se habia liberado. No se
        # confirma nada ni se avisa al cliente: el dueno decide.
        amount = payload.get("amount")
        amount_label = f" de ${amount}" if amount else ""
        return Notification(
            store_id=message.store_id,
            type=message.event_type,
            title="Pago recibido de un turno ya liberado",
            body=(
                f"{client_name} pago la seña{amount_label} de {service_name}, "
                "pero el turno ya se habia liberado. Devolvele la plata "
                "(registra el reembolso) o reasignale un turno."
            ),
            appointment_id=str(appointment_id) if appointment_id else None,
        )

    return None


async def _client_confirmation_mail(
    db: AsyncSession, appointment_id: str | None
) -> PendingEmail | None:
    """Arma (no manda) el "turno confirmado" al cliente; se despacha tras el commit."""
    if not appointment_id:
        return None
    from sqlalchemy.orm import joinedload

    from modules.stores.model import Store

    res = await db.execute(
        select(Appointment)
        .options(joinedload(Appointment.service), joinedload(Appointment.staff))
        .where(Appointment.id == appointment_id)
    )
    appointment = res.scalar_one_or_none()
    if appointment is None or appointment.status != AppointmentStatus.CONFIRMED.value:
        return None
    store = await db.get(Store, appointment.store_id)
    details = build_client_details(
        appointment, appointment.service, appointment.staff, store
    )
    return partial(
        send_confirmation_email, email=appointment.client_email, details=details
    )


async def _store_owner_mails(
    db: AsyncSession, notification: Notification
) -> list[PendingEmail]:
    """Arma (no manda) la replica por mail de la notificacion in-app, uno por
    administrador de la tienda; se despachan tras el commit.

    Es best-effort: si falla el envio no se pierde el evento, porque la
    notificacion del panel ya quedo persistida.
    """
    result = await db.execute(
        select(User.email).where(
            User.store_id == notification.store_id,
            User.role == UserRole.ADMIN,
            User.is_active.is_(True),
            User.email.is_not(None),
        )
    )
    return [
        partial(
            send_store_notification_email,
            email=email,
            title=notification.title,
            body=notification.body,
        )
        for email in result.scalars().all()
        if email
    ]


def _inbox_batch_query(
    *, limit: int, store_id: str | None
) -> Select[tuple[WebhookInbox]]:
    filters: list[ColumnElement[bool]] = [
        WebhookInbox.processed_at.is_(None),
        WebhookInbox.is_active.is_(True),
    ]
    if store_id:
        filters.append(WebhookInbox.store_id == store_id)
    return (
        select(WebhookInbox)
        .where(*filters)
        .order_by(WebhookInbox.created_at.asc())
        .limit(limit)
    )


async def process_webhook_inbox_batch(
    db: AsyncSession,
    *,
    limit: int = 100,
    store_id: str | None = None,
) -> dict[str, int]:
    async with _exclusive_job(db, INBOX_JOB_LOCK) as tomado:
        if not tomado:
            # Otra corrida del beat sigue adentro (MP lento): esta no hace nada.
            logger.info("process_webhook_inbox_overlap_skipped")
            return {"processed": 0, "failed": 0, "inspected": 0}
        return await _process_webhook_inbox_batch(db, limit=limit, store_id=store_id)


async def _process_webhook_inbox_batch(
    db: AsyncSession, *, limit: int, store_id: str | None
) -> dict[str, int]:
    """Aplica los webhooks pendientes en dos fases (AUD2-B2-02, 2026-09-20).

    Fase A, SIN lock y con la transaccion cerrada: se le pide a Mercado Pago
    el detalle de cada evento. Antes el lote tomaba las filas con ``FOR UPDATE
    SKIP LOCKED`` y hacia ese HTTP (hasta 20 s por evento) dentro del mismo
    ``for``, asi que una corrida podia sostener 100 filas bloqueadas y la
    sesion ``idle in transaction`` durante minutos (regla 5).

    Fase B, CON lock: se escribe con el resultado ya en memoria. La exclusion
    entre corridas solapadas la da ahora el advisory lock de sesion
    (``_exclusive_job``), como en el job de vencimiento: el ``SKIP LOCKED`` de
    la fase B ya no alcanza porque la fase A no bloquea nada.
    """
    consulta = _inbox_batch_query(limit=limit, store_id=store_id)
    pendientes = list((await db.execute(consulta)).scalars().all())
    # La configuracion es por tienda, no por evento: una lectura con in_()
    # antes del for en vez de dos por webhook (regla 12; 2026-09-17, B2-13).
    configs = await load_gateway_configs(db, (i.store_id for i in pendientes))
    # Commit de AsyncSession y no de TenantSession: el de TenantSession
    # reaplica el contexto y con eso reabre otra transaccion en el acto (S-02).
    await AsyncSession.commit(db)
    enriquecidos = await _enrich_inbox_payloads(db, pendientes, configs)
    await _apply_tenant_context(db)

    result = await db.execute(
        consulta.with_for_update(skip_locked=True).execution_options(
            populate_existing=True
        )
    )
    processed = 0
    failed = 0
    inspected = 0
    for inbox in result.scalars().all():
        if inbox.id not in enriquecidos:
            # Llego despues de la fase A: sin detalle de MP no se resuelve, y
            # gastarle un intento seria mentir. Lo toma la corrida siguiente.
            continue
        inspected += 1
        try:
            applied = True
            if inbox.provider == "mercadopago" and inbox.store_id:
                inbox.payload = enriquecidos[inbox.id]
                applied = await apply_mercadopago_webhook_payload(
                    db, store_id=inbox.store_id, payload=inbox.payload, configs=configs
                )
            if applied:
                inbox.mark_processed()
                processed += 1
            else:
                inbox.register_failure("No se pudo resolver el pago del webhook")
                failed += 1
        except Exception as exc:
            inbox.register_failure(str(exc))
            failed += 1

    await db.commit()
    return {"processed": processed, "failed": failed, "inspected": inspected}


async def _enrich_inbox_payloads(
    db: AsyncSession, pendientes: list[WebhookInbox], configs: GatewayConfigs
) -> dict[str, dict[str, JsonValue]]:
    """Consulta el detalle de cada webhook en MP. Sin lock ni transaccion abierta.

    Un evento que no se puede enriquecer conserva su payload crudo: ``enrich``
    ya devuelve el original ante cualquier fallo, y la fase B decide con eso.
    """
    persistir = partial(_persist_refresh_in_short_transaction, db)
    enriquecidos: dict[str, dict[str, JsonValue]] = {}
    for inbox in pendientes:
        if inbox.provider != "mercadopago" or not inbox.store_id:
            enriquecidos[inbox.id] = inbox.payload
            continue
        enriquecidos[inbox.id] = await enrich_mercadopago_webhook_payload(
            db,
            store_id=inbox.store_id,
            payload=inbox.payload,
            configs=configs,
            persist_refresh=persistir,
        )
    return enriquecidos


def _reconciliation_query(limit: int, now: datetime) -> Select[tuple[Payment]]:
    cutoff = now - timedelta(days=RECONCILIATION_LOOKBACK_DAYS)
    return (
        select(Payment)
        .join(
            PaymentGatewayConfig,
            PaymentGatewayConfig.store_id == Payment.store_id,
        )
        .where(
            Payment.status == PaymentStatus.PENDING.value,
            Payment.provider == "mercadopago",
            Payment.is_active.is_(True),
            Payment.created_at >= cutoff,
            PaymentGatewayConfig.provider == "mercadopago",
        )
        .order_by(Payment.created_at.asc())
        .limit(limit)
    )


async def reconcile_pending_payments(
    db: AsyncSession, *, limit: int = 100
) -> dict[str, int]:
    """Consulta a Mercado Pago los cobros que siguen pendientes en Shifty.

    Es la red de contencion del webhook: si la notificacion nunca llego, llego
    sin firma valida o no pudimos resolverla, aca recuperamos el estado real
    preguntandole directamente a Mercado Pago.
    """
    async with _exclusive_job(db, RECONCILE_JOB_LOCK) as tomado:
        if not tomado:
            logger.info("reconcile_pending_payments_overlap_skipped")
            return {"reconciled": 0, "failed": 0, "inspected": 0}
        return await _reconcile_pending_payments(db, limit=limit)


async def _reconcile_pending_payments(
    db: AsyncSession, *, limit: int
) -> dict[str, int]:
    """Las mismas dos fases que el inbox (AUD2-B2-02, 2026-09-20).

    Aca el costo era el peor de los tres lotes: las filas bloqueadas son
    ``payments``, las mismas que toma ``find_payment_for_webhook`` en cada
    webhook entrante y ``get_by_appointment_locked`` al liberar un turno. Con
    ``lock_timeout = 5s`` en el rol de la app y MP lento, una corrida hacia
    fallar los webhooks y el boton "liberar turno" del panel.
    """
    consulta = _reconciliation_query(limit, datetime.now(timezone.utc))
    pendientes = list((await db.execute(consulta)).scalars().all())
    # La configuracion es por tienda, no por cobro: una lectura con in_() antes
    # del for en vez de dos por cobro, una en la consulta a MP y otra en la
    # validacion de integridad (regla 12; 2026-09-20, AUD2-B2-06).
    configs = await load_gateway_configs(db, (p.store_id for p in pendientes))
    await AsyncSession.commit(db)
    remotos, fallidos = await _remote_payments_for_reconciliation(
        db, pendientes, configs
    )
    await _apply_tenant_context(db)

    result = await db.execute(
        consulta.with_for_update(skip_locked=True, of=Payment).execution_options(
            populate_existing=True
        )
    )
    reconciled = 0
    inspected = 0
    # Un cobro que aparecio despues de la fase A no tiene respuesta de MP: lo
    # toma la corrida siguiente en vez de contarse como inspeccionado.
    vistos = {p.id for p in pendientes}
    for payment in result.scalars().all():
        if payment.id not in vistos:
            continue
        inspected += 1
        remote = remotos.get(payment.id)
        if not remote:
            continue
        try:
            applied = await apply_mercadopago_webhook_payload(
                db,
                store_id=payment.store_id,
                payload={"data": remote, "status": remote.get("status")},
                configs=configs,
            )
            if applied:
                reconciled += 1
        except Exception:
            # Un pago que no se puede conciliar no debe frenar al resto del lote.
            fallidos += 1

    await db.commit()
    return {"reconciled": reconciled, "failed": fallidos, "inspected": inspected}


async def _remote_payments_for_reconciliation(
    db: AsyncSession, pendientes: list[Payment], configs: GatewayConfigs
) -> tuple[dict[str, dict[str, Any]], int]:
    """{payment.id: pago remoto} y cuantos no se pudieron consultar.

    Corre en la fase A: sin lock y con la transaccion cerrada.
    """
    persistir = partial(_persist_refresh_in_short_transaction, db)
    remotos: dict[str, dict[str, Any]] = {}
    fallidos = 0
    for payment in pendientes:
        try:
            remote = await _fetch_remote_payment(db, payment, configs, persistir)
        except Exception:
            fallidos += 1
            continue
        if remote:
            remotos[payment.id] = remote
    return remotos, fallidos


async def _fetch_remote_payment(
    db: AsyncSession,
    payment: Payment,
    configs: GatewayConfigs | None = None,
    persist_refresh: PersistRefresh | None = None,
) -> dict[str, Any] | None:
    if payment.external_payment_id:
        return await fetch_mercadopago_payment(
            db,
            store_id=payment.store_id,
            payment_id=payment.external_payment_id,
            configs=configs,
            persist_refresh=persist_refresh,
        )

    candidates = await search_mercadopago_payments(
        db,
        store_id=payment.store_id,
        external_reference=payment.appointment_id,
        configs=configs,
        persist_refresh=persist_refresh,
    )
    if not candidates:
        return None
    # Nos quedamos con un cobro acreditado si existe; si no, con el mas reciente.
    for candidate in candidates:
        if str(candidate.get("status") or "").lower() == "approved":
            return candidate
    return candidates[0]


def _expired_holds_query(
    now: datetime, limit: int
) -> Select[tuple[Appointment, Payment]]:
    """Turnos con retencion vencida y sin cobro acreditado, los mas viejos primero."""
    return (
        select(Appointment, Payment)
        .outerjoin(Payment, Payment.appointment_id == Appointment.id)
        .where(
            Appointment.status.in_(
                [
                    AppointmentStatus.PENDING.value,
                    AppointmentStatus.PENDING_PAYMENT.value,
                ]
            ),
            Appointment.expires_at.is_not(None),
            Appointment.expires_at <= now,
            or_(Payment.id.is_(None), Payment.status == PaymentStatus.PENDING.value),
        )
        .order_by(Appointment.expires_at.asc())
        .limit(limit)
    )


# Advisory locks de jobs: forma de DOS int4 (namespace, id). Postgres guarda
# esas claves aparte de las de un solo bigint (pg_locks.objsubid = 2 frente a
# 1), asi que no pueden chocar con pg_advisory_xact_lock(hashtext('ledger:...'))
# del fiado ni con ningun otro lock de un argumento. El namespace es fijo y
# reservado para jobs; el id es hashtext(nombre del job).
JOB_LOCK_NAMESPACE = 7001
EXPIRE_JOB_LOCK = "job:expire_unpaid_appointments"
# Desde AUD2-B2-02 el inbox y la conciliacion tambien leen su lote SIN lock
# (el HTTP a MP pasa a una fase previa), asi que la exclusion entre corridas
# solapadas del beat ya no puede venir del SKIP LOCKED: viene de aca.
INBOX_JOB_LOCK = "job:process_webhook_inbox"
RECONCILE_JOB_LOCK = "job:reconcile_pending_payments"


async def _release_job_lock(conn: AsyncConnection, params: dict[str, object]) -> None:
    """Suelta el lock de sesion; si no puede, invalida la conexion.

    Si ``pg_advisory_unlock`` falla por algo que no es una desconexion, la
    conexion volveria al pool con el lock de sesion tomado y ninguna corrida
    siguiente lo conseguiria. ``invalidate()`` la saca del pool: Postgres
    cierra la sesion y con ella suelta el lock. No se re-levanta: el trabajo
    del job ya esta hecho y el lock queda liberado igual.
    """
    try:
        await conn.execute(
            text("SELECT pg_advisory_unlock(:namespace, hashtext(:clave))"), params
        )
    except Exception as exc:
        logger.warning(
            "job_lock_unlock_failed",
            job=params.get("clave"),
            error_type=type(exc).__name__,
        )
        await conn.invalidate()


@asynccontextmanager
async def _exclusive_job(db: AsyncSession, name: str) -> AsyncIterator[bool]:
    """Advisory lock de SESION por tarea: una sola corrida del job a la vez.

    Se toma con ``pg_try_advisory_lock(namespace, id)`` en una conexion propia
    en AUTOCOMMIT, asi que sobrevive a los commits de la sesion del job y no
    deja ninguna transaccion abierta mientras se habla con Mercado Pago. Un
    lock de transaccion (``pg_try_advisory_xact_lock``) moriria en el commit
    previo al HTTP, y el ``FOR UPDATE SKIP LOCKED`` de la fase B tampoco
    alcanza: la fase A no bloquea nada, asi que sin esto dos corridas
    solapadas le preguntaban a MP dos veces por el mismo cobro. Se libera con
    ``pg_advisory_unlock`` al salir (o invalidando la conexion si eso falla);
    si el proceso muere, al cerrarse la conexion. En SQLite (tests) no hay
    concurrencia real: es no-op.
    """
    bind = db.bind
    if not isinstance(bind, AsyncEngine) or bind.dialect.name != "postgresql":
        yield True
        return
    async with bind.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        params: dict[str, object] = {"namespace": JOB_LOCK_NAMESPACE, "clave": name}
        tomado = bool(
            await conn.scalar(
                text("SELECT pg_try_advisory_lock(:namespace, hashtext(:clave))"),
                params,
            )
        )
        try:
            yield tomado
        finally:
            if tomado:
                await _release_job_lock(conn, params)


async def expire_unpaid_appointments(
    db: AsyncSession, *, limit: int = 100
) -> dict[str, int]:
    async with _exclusive_job(db, EXPIRE_JOB_LOCK) as tomado:
        if not tomado:
            # Otra corrida del beat sigue adentro (MP lento): esta no hace nada.
            logger.info("expire_unpaid_appointments_overlap_skipped")
            return {"expired": 0, "rescued": 0, "inspected": 0}
        return await _expire_unpaid_appointments(db, limit=limit)


async def _expire_unpaid_appointments(
    db: AsyncSession, *, limit: int
) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    vencidos = _expired_holds_query(now, limit)

    # Fase A, SIN lock: preguntarle a Mercado Pago por los cobros pendientes.
    # Es HTTP (hasta 20 s por pedido) y no puede correr con las filas del lote
    # bloqueadas: con MP degradado una corrida sostenia 100 turnos bloqueados
    # durante minutos (regla 5; incidente 2026-09-04). 2026-09-16, B2-02.
    candidatos = list((await db.execute(vencidos)).all())
    pendientes = [payment for _, payment in candidatos if payment is not None]
    # Tampoco con una transaccion abierta (S-02, 2026-09-18): la config del
    # gateway se lee ACA, una vez por tienda, y la transaccion de lectura se
    # cierra antes del HTTP. Sin esto la sesion quedaba "idle in transaction"
    # toda la fase y el idle_in_transaction_session_timeout (60 s) del rol la
    # mataba a mitad del job. Commit de AsyncSession y no de TenantSession: el
    # de TenantSession reaplica el contexto y con eso reabre otra transaccion
    # en el acto; el contexto se reaplica recien en la fase B.
    configs = await load_gateway_configs(db, (p.store_id for p in pendientes))
    await AsyncSession.commit(db)
    remotos = await _fetch_remote_payments(
        pendientes,
        db=db,
        configs=configs,
        persist_refresh=partial(_persist_refresh_in_short_transaction, db),
    )
    await _apply_tenant_context(db)

    # Fase B, CON lock: decidir con el resultado ya en memoria. Postgres
    # rechaza FOR UPDATE sobre el lado nullable de un OUTER JOIN, asi que se
    # bloquea solo la fila del turno. populate_existing: las instancias ya
    # cargadas en la fase A se refrescan con la fila bloqueada, no con lo que
    # se leyo antes de la llamada a MP.
    result = await db.execute(
        vencidos.with_for_update(skip_locked=True, of=Appointment).execution_options(
            populate_existing=True
        )
    )
    rows = list(result.all())
    expired = 0
    rescued = 0
    liberados: list[tuple[str, datetime]] = []
    for appointment, payment in rows:
        # Ultimo chequeo antes de liberar el turno: si el cobro se acredito y el
        # webhook nunca llego, vencerlo perderia una reserva ya pagada.
        if payment and await _apply_remote_payment(
            db, payment, remotos.get(payment.id)
        ):
            rescued += 1
            continue
        appointment.apply_status_transition(AppointmentStatus.EXPIRED)
        if payment:
            # Por el grafo, no por asignacion directa: si el cobro ya estaba
            # acreditado no puede degradarse a expirado.
            stamp_payment_from_status(payment, PaymentStatus.EXPIRED.value)
        publish_slot_released(
            db,
            store_id=appointment.store_id,
            staff_id=appointment.staff_id,
            service_id=appointment.service_id,
            appointment_id=appointment.id,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            reason="hold_expired",
        )
        expired += 1
        liberados.append((appointment.store_id, appointment.starts_at))
    await db.commit()
    # El cupo vuelve a estar libre: la pagina publica no puede seguir
    # mostrandolo ocupado cinco minutos mas. Redis caido no frena el job.
    if liberados:
        try:
            redis = await get_redis()
            for store_id, starts_at in liberados:
                await invalidate_availability(redis, store_id, starts_at)
        except (RedisError, OSError) as exc:
            logger.warning("availability_cache_invalidation_failed", error=str(exc))
    return {"expired": expired, "rescued": rescued, "inspected": len(rows)}


async def _persist_refresh_in_short_transaction(
    db: AsyncSession, config: PaymentGatewayConfig
) -> None:
    """Persiste en el acto la config que un 401 hizo refrescar, en una
    transaccion corta propia, y la cierra antes de la siguiente llamada a MP.

    Revision de S-02 (2026-09-18): el refresh hacia ``db.flush()`` en una
    transaccion NUEVA, sin el contexto de la tarea. En Postgres la RLS de
    ``payment_gateway_configs`` dejaba el UPDATE en 0 filas (StaleDataError),
    la sesion quedaba inactiva y la corrida moria para todas las tiendas; y
    en cualquier motor esa transaccion seguia abierta durante el resto del
    HTTP. Se persiste YA (no en la fase B) porque MP puede rotar el refresh
    token: si la corrida muriera antes, la conexion OAuth de la tienda
    quedaria rota. Si la escritura falla se deshace sin reaplicar contexto
    (nada queda abierto) y el error sigue al llamador, que saltea ese cobro.
    """
    try:
        await _apply_tenant_context(db)
        await db.flush([config])
        await AsyncSession.commit(db)
    except Exception:
        await AsyncSession.rollback(db)
        raise


async def _fetch_remote_payments(
    payments: list[Payment],
    *,
    db: AsyncSession,
    configs: GatewayConfigs,
    persist_refresh: PersistRefresh | None = None,
) -> dict[str, dict[str, Any]]:
    """Una request HTTP a Mercado Pago por cobro pendiente: {payment.id: pago remoto}.

    Se llama sin ningun lock tomado. Si no se puede preguntar por un cobro, no
    figura en el resultado y el turno vence: la conciliacion posterior va a
    detectar el cobro y dejarlo visible para reembolso.
    """
    remotos: dict[str, dict[str, Any]] = {}
    for payment in payments:
        if payment.provider != "mercadopago":
            continue
        try:
            remote = await _fetch_remote_payment(db, payment, configs, persist_refresh)
        except Exception:
            continue
        if remote:
            remotos[payment.id] = remote
    return remotos


async def _apply_remote_payment(
    db: AsyncSession, payment: Payment, remote: dict[str, Any] | None
) -> bool:
    """Aplica el pago remoto (ya consultado) y dice si el cobro quedo acreditado.

    Escribe sobre el pago y el turno: corre con la fila del turno bloqueada.
    """
    if not remote:
        return False
    applied = await apply_mercadopago_webhook_payload(
        db,
        store_id=payment.store_id,
        payload={"data": remote, "status": remote.get("status")},
    )
    return applied and payment.status in {
        PaymentStatus.APPROVED.value,
        PaymentStatus.MANUAL_CONFIRMED.value,
    }
