from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import Row, Select, or_, select, text
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from core.availability_cache import invalidate_availability
from core.config import settings
from core.database import _apply_tenant_context
from core.redis import REDIS_UNAVAILABLE_ERRORS, get_availability_cache
from core.utils import ensure_utc_aware
from modules.appointments.model import Appointment, AppointmentStatus
from modules.notifications.model import Notification, NotificationType
from modules.notifications.tasks import (
    EVENT_APPOINTMENT_BOOKED_BY_PANEL,
    EVENT_APPOINTMENT_COMPLETED,
    EVENT_APPOINTMENT_CONFIRMED,
    EVENT_APPOINTMENT_RESCHEDULED,
    build_client_details,
    send_waitlist_offer_email,
    format_local_datetime,
    send_cancellation_email,
    send_confirmation_email,
    send_rebook_email,
    send_reschedule_email,
    send_store_notification_email,
    smtp_session,
)
from modules.payments.links import RETIRED_LINK_SEARCH_MAX, retired_link_references
from modules.payments.model import (
    LIVE_CHARGE_PAYMENT_STATUSES,
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
    mercadopago_budget,
    stamp_payment_from_status,
    search_mercadopago_payments,
)

# Ventana hacia atras que revisa la conciliacion. Mas alla de esto un pago
# pendiente ya se considera abandonado.
RECONCILIATION_LOOKBACK_DAYS = 30


# Inbox, conciliacion y vencimiento de retenciones (F1-20, R9-08): lote de 25
# y presupuesto de 60 s para la fase A. Antes eran 100 filas x hasta 20 s por
# consulta a MP sin tope: con MP lento el hard time limit de Celery (150 s)
# mataba la tarea antes de la fase B, no se aplicaba nada y la corrida
# siguiente retomaba las mismas 100. El presupuesto se mira ANTES de cada
# consulta, y cada consulta corre con ``mercadopago_budget`` de
# ``MP_QUERY_BUDGET_SECONDS``: la cadena entera de una consulta (un 401, el
# refresh OAuth y el reintento: hasta 3 requests de 20 s) no pasa de 20 s.
# Peor caso: 60 + 20 = 80 s, por debajo del soft time limit (120 s); antes de
# ese tope por consulta llegaba a 60 + 60 (revision de 3b977a9..6c84d46, #3).
# Lo que no entra no gasta un intento: lo toma la corrida siguiente.
MP_BATCH_LIMIT = 25
MP_PHASE_A_BUDGET_SECONDS = 60.0
MP_QUERY_BUDGET_SECONDS = 20.0


def _reloj() -> float:
    """Reloj de los presupuestos de la fase A; los tests lo reemplazan."""
    return time.monotonic()


def _presupuesto_agotado(limite: float, *, job: str, sin_consultar: int) -> bool:
    """True (y lo deja en el log) si la fase A ya no puede consultar a MP."""
    if _reloj() < limite:
        return False
    logger.warning(
        "mp_phase_a_budget_exhausted",
        job=job,
        sin_consultar=sin_consultar,
        budget_seconds=MP_PHASE_A_BUDGET_SECONDS,
    )
    return True


class _PresupuestoAgotado(Exception):
    """La fase A se quedo sin presupuesto ANTES de una consulta a MP, quizas a
    mitad de un cobro (revision de e5579b6..3b977a9, #1). El cobro cortado no
    cuenta como consultado: lo toma la corrida siguiente."""


def _consultar_si_alcanza(limite: float | None) -> None:
    """Se llama antes de CADA consulta a MP; ``None`` = sin presupuesto."""
    if limite is not None and _reloj() >= limite:
        raise _PresupuestoAgotado()


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


# Funcion de envio de un mail del outbox (``send_*_email`` de notifications).
# Conserva is_deliverable_email y el best-effort de cada camino.
PendingEmail = Callable[..., Awaitable[object]]

# AUD2-B4-02 (2026-09-20): el despacho post-commit no tenia tope. El lote trae
# hasta 100 mensajes (500 por el endpoint del panel) y cada mensaje puede
# generar varios mails; con un SMTP lento el hard time limit de Celery (150 s)
# mataba el proceso con los ``processed_at`` YA persistidos, asi que los mails
# que faltaban no salian nunca y no quedaba rastro. Desde entonces el despacho
# corre con una sola conexion SMTP y con presupuesto.
#
# 45 s y no 90 (v-diff de AUD2-B4-02, 2026-09-20): el rol de la app tiene
# ``idle_in_transaction_session_timeout = 60 s`` (migracion app_role_timeouts).
# El despacho corre sin transaccion abierta, pero el presupuesto tiene que
# quedar igual por debajo de ese tope con margen: se revisa ANTES de cada envio
# y el envio en curso puede sumar hasta los 10 s del timeout del SMTP. Si
# alguna vez vuelve a quedar una transaccion idle durante el despacho, Postgres
# no llega a matar la conexion antes de anotar los fallos.
OUTBOX_EMAIL_BUDGET_SECONDS = 45

# F2-03 (plan de rendimiento, R9-06, 2026-09-24): lo que el presupuesto no
# alcanzaba se anotaba con ``register_failure`` y se perdia; con una rafaga, la
# mitad de los mails de cada tick. Ahora cada mail es su propia fila del outbox,
# ``email.send``, escrita en la MISMA transaccion del lote que lo genera (antes
# del commit): si el worker muere despues del commit, el mail sigue en la base.
# El despacho reclama esas filas de a una (``processed_at`` + commit, con
# ``SKIP LOCKED``) y recien despues manda; lo que no entra en el presupuesto
# queda pendiente y sale en el tick siguiente (20 s). ``processed_at`` nunca se
# reabre: el reclamo va antes del envio y un envio fallido no se reintenta (el
# DATA pudo haber llegado), queda con ``attempts`` y ``error``.
EVENT_EMAIL_SEND = "email.send"


@dataclass(frozen=True)
class _Mail:
    """Un mail del outbox descrito con datos: se guarda en una fila ``email.send``.

    ``kind`` elige la funcion de envio (``_sender``) y ``kwargs`` son sus
    argumentos, ya resueltos al planear el evento (JSON).
    """

    kind: str
    kwargs: dict[str, Any]


def _sender(kind: str) -> PendingEmail | None:
    """Funcion de envio de cada tipo de mail, resuelta al momento de mandar."""
    envios: dict[str, PendingEmail] = {
        "waitlist_offer": send_waitlist_offer_email,
        "cancellation": send_cancellation_email,
        "confirmation": send_confirmation_email,
        "store_notification": send_store_notification_email,
        "rebook": send_rebook_email,
        "reschedule": send_reschedule_email,
    }
    return envios.get(kind)


# F2-02 (2026-09-24): eventos del panel que terminan en un mail al cliente,
# con el mail que les toca y los estados en los que el turno tiene que seguir
# para que el aviso tenga sentido (el lote relee el turno: entre el evento y el
# tick pudo cambiar).
_ABIERTOS = frozenset(
    {
        AppointmentStatus.PENDING.value,
        AppointmentStatus.PENDING_PAYMENT.value,
        AppointmentStatus.CONFIRMED.value,
    }
)
_MAILS_DEL_PANEL: dict[str, tuple[str, frozenset[str]]] = {
    EVENT_APPOINTMENT_BOOKED_BY_PANEL: ("confirmation", _ABIERTOS),
    EVENT_APPOINTMENT_CONFIRMED: (
        "confirmation",
        frozenset({AppointmentStatus.CONFIRMED.value}),
    ),
    EVENT_APPOINTMENT_COMPLETED: (
        "rebook",
        frozenset({AppointmentStatus.COMPLETED.value}),
    ),
    EVENT_APPOINTMENT_RESCHEDULED: ("reschedule", _ABIERTOS),
}


def _contexto_del_mail(message: OutboxMessage) -> dict[str, str | None]:
    """De que tienda y turno es un mail del outbox, para el log si no sale.

    Solo identificadores: ni email ni nombre del cliente (S-04, 2026-09-18;
    se habian perdido al sacar los envios de la transaccion en B2-01). Una fila
    ``email.send`` informa el evento que la genero.
    """
    payload = message.payload if isinstance(message.payload, dict) else {}
    turno = payload.get("appointment_id") or payload.get("public_id")
    evento = message.event_type
    if evento == EVENT_EMAIL_SEND:
        evento = str(payload.get("source_event") or evento)
    return {
        "store_id": message.store_id,
        "appointment_id": str(turno) if turno else None,
        "event_type": evento,
    }


def _persistir_mails(
    db: AsyncSession, message: OutboxMessage, mails: list[_Mail]
) -> None:
    """Una fila ``email.send`` por mail, en la transaccion del evento (F2-03)."""
    contexto = _contexto_del_mail(message)
    for mail in mails:
        db.add(
            OutboxMessage(
                store_id=message.store_id,
                event_type=EVENT_EMAIL_SEND,
                payload={
                    "mail": mail.kind,
                    "args": mail.kwargs,
                    "source_event": message.event_type,
                    "appointment_id": contexto["appointment_id"],
                },
            )
        )


async def _registrar_fallo(
    db: AsyncSession, fila: OutboxMessage | WebhookInbox, exc: Exception
) -> None:
    """Suma el intento fallido, en su propio savepoint (AUD2-B2-11).

    Los tres lotes envuelven cada item en ``except Exception`` y siguen. Eso
    esta bien para un error de Mercado Pago, pero si la excepcion venia de la
    BASE (``IntegrityError``, ``StaleDataError``, deadlock) la transaccion
    quedaba abortada: cada iteracion siguiente fallaba, ``register_failure``
    no se persistia y el ``db.commit()`` final reventaba. Se perdia el lote
    entero, incluidos los items ya aplicados, y ``attempts`` no subia, asi que
    el mismo lote se repetia cada minuto sin avanzar (regla 8, y el techo de
    B2-12 deja de funcionar si ``attempts`` nunca se persiste). Por eso cada
    item corre bajo ``begin_nested``.

    Esta anotacion tiene que ser un savepoint y no una escritura suelta: lo que queda
    pendiente en la transaccion externa lo termina volcando el ``flush`` del
    savepoint del item SIGUIENTE, y si ese item falla se revierte tambien
    este ``attempts``. Con savepoint propio, el intento queda firme apenas se
    libera. Si ni siquiera eso se puede escribir, se registra y se sigue: el
    lote no se pierde por no poder anotar un fallo.

    El soft time limit de Celery NO es un fallo del item (revision de f2b,
    2026-09-24): ``SoftTimeLimitExceeded`` es una ``Exception`` y anotarlo
    gastaba un ``attempts`` (regla 7) y dejaba seguir al lote hasta el hard
    limit. Todo ``except Exception`` de este modulo lo deja pasar antes
    (``tests/architecture/test_corte_de_tiempo_no_se_traga.py``).
    """
    if isinstance(exc, SoftTimeLimitExceeded):
        raise exc
    try:
        # Revertir el savepoint deja la fila EXPIRADA: ``register_failure``
        # lee ``attempts`` y ese acceso perezoso, fuera de un await, revienta
        # con ``MissingGreenlet``. Se relee explicitamente antes de tocarla.
        await db.refresh(fila)
        async with db.begin_nested():
            fila.register_failure(str(exc))
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        logger.warning(
            "batch_register_failure_skipped",
            error_type=type(exc).__name__,
            row_id=fila.id,
        )


@dataclass(frozen=True)
class _ContextoDelLote:
    """Lo que los mensajes del lote comparten por tienda, leido una vez (F1-23).

    Antes cada aviso al dueno consultaba los admins de SU tienda y cada "sena
    acreditada" leia su ``Store``: hasta dos SELECT por mensaje dentro de la
    transaccion del ``FOR UPDATE SKIP LOCKED`` (R3-07, regla 12).
    """

    admins: Mapping[str, list[str]]
    tiendas: Mapping[str, Any]
    # appointment_id -> turno (None si no existe) de los mensajes que mandan
    # un mail al cliente: la sena acreditada y los eventos del panel (F2-02).
    turnos: Mapping[str, Appointment | None]


# Eventos que no generan aviso al dueno: no necesitan sus admins. Los del
# panel (F2-02) solo le escriben al cliente.
_EVENTOS_SIN_AVISO_AL_DUENO = frozenset(
    {EVENT_SLOT_RELEASED, "appointment.cancelled_by_block", *_MAILS_DEL_PANEL}
)
# Eventos con mail al cliente: necesitan su turno y su tienda.
_EVENTOS_CON_MAIL_AL_CLIENTE = frozenset(
    {NotificationType.PAYMENT_APPROVED.value, *_MAILS_DEL_PANEL}
)


def _turnos_con_detalle(ids: list[str]) -> Select[tuple[Appointment]]:
    from sqlalchemy.orm import joinedload

    return (
        select(Appointment)
        .options(joinedload(Appointment.service), joinedload(Appointment.staff))
        .where(Appointment.id.in_(ids))
    )


async def _contexto_del_lote(
    db: AsyncSession, messages: list[OutboxMessage]
) -> _ContextoDelLote:
    """Admins y tiendas del lote con un ``in_()`` cada uno, filtrados por tienda."""
    from modules.stores.model import Store

    con_aviso = {
        m.store_id
        for m in messages
        if m.store_id and m.event_type not in _EVENTOS_SIN_AVISO_AL_DUENO
    }
    admins: dict[str, list[str]] = {}
    if con_aviso:
        filas = await db.execute(
            select(User.store_id, User.email).where(
                User.store_id.in_(con_aviso),
                User.role == UserRole.ADMIN,
                User.is_active.is_(True),
                User.email.is_not(None),
            )
        )
        for store_id, email in filas.all():
            if store_id and email:
                admins.setdefault(store_id, []).append(email)
    con_mail = [
        m
        for m in messages
        if m.store_id and m.event_type in _EVENTOS_CON_MAIL_AL_CLIENTE
    ]
    tiendas: dict[str, Any] = {}
    turnos: dict[str, Appointment | None] = {}
    if con_mail:
        leidas = await db.execute(
            select(Store).where(Store.id.in_({m.store_id for m in con_mail}))
        )
        tiendas = {tienda.id: tienda for tienda in leidas.scalars().all()}
        ids = sorted(
            {
                str(m.payload.get("appointment_id"))
                for m in con_mail
                if isinstance(m.payload, dict) and m.payload.get("appointment_id")
            }
        )
        turnos = {turno_id: None for turno_id in ids}
        if ids:
            for turno in (await db.execute(_turnos_con_detalle(ids))).scalars():
                turnos[turno.id] = turno
    return _ContextoDelLote(admins=admins, tiendas=tiendas, turnos=turnos)


async def _plan_outbox_message(
    db: AsyncSession,
    message: OutboxMessage,
    *,
    now: datetime,
    contexto_del_lote: _ContextoDelLote,
) -> list[_Mail]:
    """Aplica en la base lo que pide un evento y devuelve sus mails.

    Extraida de ``process_outbox_batch`` (regla 29): el lote se queda con el
    lock, el conteo y el manejo de fallos; el despacho por tipo de evento vive
    aca. Solo persiste y describe: ningun mail sale dentro de la transaccion
    del lote (2026-09-16, B2-01); el lote los guarda como filas ``email.send``
    (F2-03) y salen despues del commit.
    """
    if message.event_type == EVENT_SLOT_RELEASED and message.store_id:
        # Lista de espera: aviso al dueno y oferta a una persona por vez.
        oferta = await offer_released_slot(
            db,
            ReleasedSlot.from_payload(message.store_id, dict(message.payload or {})),
            now=now,
        )
        if not oferta.pending_email:
            return []
        return [
            _Mail(
                "waitlist_offer",
                {
                    "email": oferta.pending_email.email,
                    "details": oferta.pending_email.details,
                },
            )
        ]

    if message.event_type == "appointment.cancelled_by_block":
        # Aviso al cliente (no al dueno, que fue quien bloqueo).
        payload = dict(message.payload or {})
        return [
            _Mail(
                "cancellation",
                {
                    "email": str(payload.get("client_email") or "") or None,
                    "details": payload,
                },
            )
        ]

    if message.event_type in _MAILS_DEL_PANEL:
        return await _panel_client_mail(db, message, contexto_del_lote)

    notification = _replaced_link_notification(message) or _build_store_notification(
        message
    )
    if notification is None:
        return []
    # La notificacion in-app es la fuente durable; el mail es un efecto
    # secundario que sale despues del commit.
    db.add(notification)
    mails = _store_owner_mails(
        notification, contexto_del_lote.admins.get(notification.store_id, [])
    )
    if message.event_type == NotificationType.PAYMENT_APPROVED.value:
        # La sena acreditada confirma el turno: el cliente tambien se entera.
        confirmacion = await _client_confirmation_mail(
            db, notification.appointment_id, contexto_del_lote
        )
        if confirmacion is not None:
            mails.append(confirmacion)
    return mails


async def process_outbox_tick(db: AsyncSession, *, limit: int) -> dict[str, int]:
    """Un tick del beat sobre el outbox: una sola corrida a la vez (F0-17).

    Con el beat cada 20 s y un lote que puede durar su presupuesto de 45 s,
    dos hijos del worker procesaban lotes en paralelo. El ``FOR UPDATE SKIP
    LOCKED`` del lote evita que tomen la MISMA fila, pero no que dos lotes
    despachen a la vez y compitan por el SMTP y el pool. El advisory lock de
    sesion (``_exclusive_job``, como el inbox y la conciliacion) deja pasar a
    uno; el otro no hace nada y el proximo tick retoma. ``process_outbox_batch``
    queda sin este lock para el endpoint del panel y conserva su SKIP LOCKED.
    """
    async with _exclusive_job(db, OUTBOX_JOB_LOCK) as tomado:
        if not tomado:
            logger.info("process_outbox_overlap_skipped")
            return {"processed": 0, "failed": 0, "inspected": 0}
        return await process_outbox_batch(db, limit=limit)


async def process_outbox_batch(
    db: AsyncSession,
    *,
    limit: int = 100,
    store_id: str | None = None,
    incluir_vencimientos: bool = True,
) -> dict[str, int]:
    """Procesa un lote del outbox: persiste, commitea y recien despues manda.

    Los mails quedan como filas ``email.send`` antes del commit (F2-03) y los
    manda ``_dispatch_pending_emails``. El commit es el de ``AsyncSession``:
    el de ``TenantSession`` reaplica el contexto y deja una transaccion IDLE
    que el rol mata a 60 s (AUD2-B4-02).
    """
    filters: list[ColumnElement[bool]] = [
        OutboxMessage.processed_at.is_(None),
        OutboxMessage.is_active.is_(True),
        # Los vencimientos de links de MP tienen su propio paso (abajo): asi
        # los mails de este lote no esperan a Mercado Pago (B1-04). Es un
        # predicado mas sobre las filas del indice parcial ix_outbox_pending.
        OutboxMessage.event_type != EVENT_PREFERENCE_EXPIRE,
        # Los mails (F2-03) los reclama el despacho, de a uno.
        OutboxMessage.event_type != EVENT_EMAIL_SEND,
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
    processed, failed = await _plan_lote(db, messages)
    # Commit plano de AsyncSession, no el de TenantSession (ver docstring).
    await AsyncSession.commit(db)
    # Recien ahora, con la transaccion cerrada y processed_at persistido, se
    # mandan los mails. Un SMTP caido no revierte nada, no marca el evento
    # como fallido ni duplica envios.
    await _dispatch_pending_emails(db, store_id=store_id)
    # El commit plano dejo la conexion sin contexto: se reaplica antes de
    # volver a leer, o la RLS le esconderia los eventos al job.
    await _apply_tenant_context(db)
    # El paso propio de los vencimientos de MP: hasta MAX_CLAIMS llamadas de
    # WORST_CASE_PER_CLAIM cada una, que ``limit`` no acota. Unico paso que
    # sale a la red, y por eso el endpoint del panel lo apaga (AUD2-B2-07).
    vencimientos = (
        await _claim_and_expire_preferences(db, store_id=store_id)
        if incluir_vencimientos
        else {"processed": 0, "failed": 0, "inspected": 0}
    )
    return {
        "processed": processed + vencimientos["processed"],
        "failed": failed + vencimientos["failed"],
        "inspected": len(messages) + vencimientos["inspected"],
    }


async def _plan_lote(
    db: AsyncSession, messages: list[OutboxMessage]
) -> tuple[int, int]:
    """Planea cada mensaje del lote en su savepoint: (procesados, fallidos).

    Extraida de ``process_outbox_batch`` al integrar F1-23 con F2-03 (regla
    29). Ningun mail sale aca: el for solo persiste (los mails como filas
    ``email.send``) y se despachan despues del commit (B2-01, F2-03).
    """
    contexto_del_lote = await _contexto_del_lote(db, messages)
    now = datetime.now(timezone.utc)
    processed = 0
    failed = 0
    for message in messages:
        try:
            # Savepoint por item (AUD2-B2-11, ver _registrar_fallo). El
            # sellado va ADENTRO: lo tiene que volcar el flush de ESTE
            # savepoint y no el del item siguiente, que puede revertirlo.
            async with db.begin_nested():
                mails = await _plan_outbox_message(
                    db, message, now=now, contexto_del_lote=contexto_del_lote
                )
                _persistir_mails(db, message, mails)
                message.processed_at = now
                message.error = None
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            failed += 1
            await _registrar_fallo(db, message, exc)
        else:
            processed += 1
    return processed, failed


async def _dispatch_pending_emails(
    db: AsyncSession, *, store_id: str | None = None
) -> None:
    """Manda los mails pendientes del outbox fuera de toda transaccion.

    AUD2-B4-02 (2026-09-20): una conexion SMTP para todo el despacho, como el
    lote de recordatorios desde B4-08, y presupuesto de tiempo para que el
    hard limit de Celery no corte en silencio.

    F2-03 (2026-09-24): cada mail es una fila ``email.send`` (la escribio el
    lote antes de su commit). Ciclo por mail: presupuesto -> reclamo
    (``processed_at`` + commit plano, ``SKIP LOCKED``) -> envio. Lo que el
    presupuesto no alcanza queda pendiente, sin intento contado, y lo toma el
    tick siguiente: ya no se pierde. Toma tambien los que dejo un tick
    anterior. Un envio fallido no se reintenta (el DATA pudo haber llegado):
    su fila queda procesada con ``attempts`` y ``error``, anotados al final
    en una transaccion nueva con el contexto reaplicado.

    Mientras se manda no hay transaccion abierta (regla 5): el reclamo
    commitea con ``AsyncSession.commit`` y no con el de ``TenantSession``,
    que reaplica el contexto y deja una idle (v-diff de AUD2-B4-02).
    """
    deadline = time.monotonic() + OUTBOX_EMAIL_BUDGET_SECONDS
    fallados: list[tuple[OutboxMessage, str]] = []
    intentados = 0
    async with smtp_session() as smtp:
        while True:
            if time.monotonic() >= deadline:
                logger.warning(
                    "outbox_email_budget_deferred",
                    attempted=intentados,
                    budget_seconds=OUTBOX_EMAIL_BUDGET_SECONDS,
                )
                break
            fila = await _claim_next_email(db, store_id=store_id)
            if fila is None:
                break
            intentados += 1
            motivo = await _send_one_pending_email(fila, smtp)
            if motivo is not None:
                fallados.append((fila, motivo))
    if not fallados:
        return
    await _apply_tenant_context(db)
    for fila, motivo in fallados:
        fila.register_failure(motivo)
    await AsyncSession.commit(db)


async def _claim_next_email(
    db: AsyncSession, *, store_id: str | None
) -> OutboxMessage | None:
    """Reclama el mail pendiente mas viejo y commitea ANTES de mandarlo.

    Con ``SKIP LOCKED`` dos despachos (el tick y el endpoint del panel) nunca
    toman la misma fila; con el reclamo commiteado antes del envio, un mail
    sale a lo sumo una vez.
    """
    await _apply_tenant_context(db)
    filtros: list[ColumnElement[bool]] = [
        OutboxMessage.event_type == EVENT_EMAIL_SEND,
        OutboxMessage.processed_at.is_(None),
        OutboxMessage.is_active.is_(True),
    ]
    if store_id:
        filtros.append(OutboxMessage.store_id == store_id)
    fila = (
        await db.execute(
            select(OutboxMessage)
            .where(*filtros)
            .order_by(OutboxMessage.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if fila is not None:
        fila.processed_at = datetime.now(timezone.utc)
    await AsyncSession.commit(db)
    return fila


async def _send_one_pending_email(fila: OutboxMessage, smtp: Any) -> str | None:
    """Manda el mail de una fila ``email.send``. Devuelve el motivo si no salio."""
    contexto = _contexto_del_mail(fila)
    payload = fila.payload if isinstance(fila.payload, dict) else {}
    enviar = _sender(str(payload.get("mail") or ""))
    argumentos = payload.get("args")
    if enviar is None or not isinstance(argumentos, dict):
        logger.warning("outbox_email_skipped", error_type="unknown_mail", **contexto)
        return "unknown_mail"
    try:
        resultado = await enviar(smtp=smtp, **argumentos)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        logger.warning(
            "outbox_email_skipped",
            error_type=type(exc).__name__,
            **contexto,
        )
        return type(exc).__name__
    if not isinstance(resultado, dict) or resultado.get("status") != "failed":
        return None
    # El sink ya logueo el error con el destinatario enmascarado.
    logger.warning("outbox_email_skipped", error_type="smtp", **contexto)
    return str(resultado.get("reason") or "smtp")


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
                persist_refresh=partial(persist_gateway_refresh, db),
            )
            errores[reclamo.message_id] = (reclamo, None)
        except SoftTimeLimitExceeded:
            raise
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


def _replaced_link_notification(message: OutboxMessage) -> Notification | None:
    """Aviso de plata recibida por un link reemplazado (perf/f4-pay).

    Aparte de ``_build_store_notification`` (deuda de la regla 29: no se
    apila otra rama ahi).
    """
    if message.event_type != NotificationType.PAYMENT_ON_REPLACED_LINK.value:
        return None
    payload = dict(message.payload or {})
    amount = payload.get("amount")
    amount_label = f" de ${amount}" if amount else ""
    appointment_id = payload.get("appointment_id")
    if payload.get("duplicado"):
        titulo = "Pago duplicado"
        # "Duplicado" incluye un cobro devuelto o con contracargo: no se dice
        # "ya estaba pagado" (revision de e5579b6..3b977a9, #6).
        cuerpo = (
            f"Entro un pago{amount_label} por un link viejo de un turno que ya "
            "tenia un pago registrado: no se aplico. Revisalo en Mercado Pago y "
            "devolvelo."
        )
    else:
        titulo = "Se recibio un pago sobre un link reemplazado"
        cuerpo = (
            f"Entro un pago{amount_label} por un link de pago que ya habias "
            "reemplazado: no se aplico al turno. Revisalo en Mercado Pago y, si "
            "corresponde, devolvelo."
        )
    return Notification(
        store_id=message.store_id,
        type=message.event_type,
        title=titulo,
        body=cuerpo,
        appointment_id=str(appointment_id) if appointment_id else None,
    )


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

    if message.event_type == NotificationType.PAYMENT_IN_MEDIATION.value:
        # V-diff de AUD2-B2-04: el cobro sigue acreditado, la plata retenida.
        amount = payload.get("amount")
        amount_label = f" de ${amount}" if amount else ""
        return Notification(
            store_id=message.store_id,
            type=message.event_type,
            title="Disputa abierta en Mercado Pago",
            body=(
                f"Mercado Pago abrio una disputa sobre el cobro{amount_label} de "
                f"{client_name} por {service_name}: la plata queda retenida hasta "
                "que se resuelva. El turno sigue confirmado."
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


async def _load_client_mail(
    db: AsyncSession,
    appointment_id: str | None,
    contexto_del_lote: _ContextoDelLote,
    store_id: str | None = None,
) -> tuple[Appointment, Any, dict[str, Any]] | None:
    """(turno, tienda, detalles de plantilla) para un mail al cliente.

    Turno y tienda ya los leyo el lote con un ``in_()`` (F1-23, regla 12);
    antes eran dos SELECT por mensaje. La consulta suelta queda solo para un
    turno que el lote no pidio.
    """
    if not appointment_id:
        return None
    from modules.stores.model import Store

    if appointment_id in contexto_del_lote.turnos:
        appointment = contexto_del_lote.turnos[appointment_id]
    else:
        appointment = (
            await db.execute(_turnos_con_detalle([appointment_id]))
        ).scalar_one_or_none()
    if appointment is None or (store_id and appointment.store_id != store_id):
        return None
    store = contexto_del_lote.tiendas.get(appointment.store_id) or await db.get(
        Store, appointment.store_id
    )
    details = build_client_details(
        appointment, appointment.service, appointment.staff, store
    )
    return appointment, store, details


async def _client_confirmation_mail(
    db: AsyncSession, appointment_id: str | None, contexto_del_lote: _ContextoDelLote
) -> _Mail | None:
    """Describe (no manda) el "turno confirmado" al cliente."""
    cargado = await _load_client_mail(db, appointment_id, contexto_del_lote)
    if cargado is None:
        return None
    appointment, _store, details = cargado
    if appointment.status != AppointmentStatus.CONFIRMED.value:
        return None
    return _Mail(
        "confirmation", {"email": appointment.client_email, "details": details}
    )


async def _panel_client_mail(
    db: AsyncSession, message: OutboxMessage, contexto_del_lote: _ContextoDelLote
) -> list[_Mail]:
    """Describe el mail al cliente de un evento del panel (F2-02).

    El turno se relee: si ya no esta en un estado que haga cierto el aviso (un
    "turno confirmado" de un turno que se cancelo antes del tick), no sale.
    El completado respeta el interruptor de mails automaticos de la tienda,
    como los recordatorios. Si el payload trae ``email`` (aunque sea nulo),
    pisa el del turno: la reserva desde la lista de espera avisa al email que
    dejo esa persona, y a nadie si no dejo uno.
    """
    kind, estados = _MAILS_DEL_PANEL[message.event_type]
    payload = message.payload if isinstance(message.payload, dict) else {}
    cargado = await _load_client_mail(
        db,
        str(payload.get("appointment_id") or ""),
        contexto_del_lote,
        message.store_id,
    )
    if cargado is None:
        return []
    appointment, store, details = cargado
    if appointment.status not in estados:
        return []
    if kind == "rebook" and not getattr(store, "send_email_reminders", True):
        return []
    email = payload["email"] if "email" in payload else appointment.client_email
    return [_Mail(kind, {"email": email, "details": details})]


def _store_owner_mails(notification: Notification, admins: list[str]) -> list[_Mail]:
    """Describe (no manda) la replica por mail de la notificacion in-app, uno
    por administrador de la tienda.

    Los admins los resolvio el lote con un ``in_()`` (F1-23). Es best-effort:
    si falla el envio no se pierde el evento, porque la notificacion del panel
    ya quedo persistida.
    """
    return [
        _Mail(
            "store_notification",
            {"email": email, "title": notification.title, "body": notification.body},
        )
        for email in admins
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
    limit: int = MP_BATCH_LIMIT,
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

    filas = await _inbox_fase_b(db, list(enriquecidos))
    processed = 0
    failed = 0
    inspected = 0
    for inbox in filas:
        inspected += 1
        try:
            # Savepoint por item (AUD2-B2-11): ver el comentario del lote del
            # outbox. Un fallo de base en un webhook no puede llevarse puestos
            # los cobros que el resto del lote ya aplico.
            async with db.begin_nested():
                applied = True
                if inbox.provider == "mercadopago" and inbox.store_id:
                    inbox.payload = enriquecidos[inbox.id]
                    applied = await apply_mercadopago_webhook_payload(
                        db,
                        store_id=inbox.store_id,
                        payload=inbox.payload,
                        configs=configs,
                    )
                if applied:
                    inbox.mark_processed()
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            failed += 1
            await _registrar_fallo(db, inbox, exc)
        else:
            if applied:
                processed += 1
            else:
                failed += 1
                await _registrar_fallo(
                    db, inbox, RuntimeError("No se pudo resolver el pago del webhook")
                )

    await db.commit()
    return {"processed": processed, "failed": failed, "inspected": inspected}


async def _inbox_fase_b(db: AsyncSession, ids: list[str]) -> list[WebhookInbox]:
    """Filas de la fase B, CON lock: SOLO las que la fase A consulto (F1-20).

    Lo que llego despues o no entro en el presupuesto no tiene detalle de MP,
    y gastarle un intento seria mentir: lo toma la corrida siguiente.
    """
    if not ids:
        return []
    result = await db.execute(
        select(WebhookInbox)
        .where(
            WebhookInbox.id.in_(ids),
            WebhookInbox.processed_at.is_(None),
            WebhookInbox.is_active.is_(True),
        )
        .order_by(WebhookInbox.created_at.asc())
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


async def _enrich_inbox_payloads(
    db: AsyncSession, pendientes: list[WebhookInbox], configs: GatewayConfigs
) -> dict[str, dict[str, JsonValue]]:
    """Consulta el detalle de cada webhook en MP. Sin lock ni transaccion abierta.

    Un evento que no se puede enriquecer conserva su payload crudo: ``enrich``
    ya devuelve el original ante cualquier fallo, y la fase B decide con eso.
    Con el presupuesto agotado deja de consultar: lo que falta no figura en el
    resultado y la fase B no lo toca (F1-20).
    """
    persistir = partial(persist_gateway_refresh, db)
    enriquecidos: dict[str, dict[str, JsonValue]] = {}
    limite = _reloj() + MP_PHASE_A_BUDGET_SECONDS
    for indice, inbox in enumerate(pendientes):
        if inbox.provider != "mercadopago" or not inbox.store_id:
            enriquecidos[inbox.id] = inbox.payload
            continue
        if _presupuesto_agotado(
            limite, job="inbox", sin_consultar=len(pendientes) - indice
        ):
            break
        with mercadopago_budget(MP_QUERY_BUDGET_SECONDS):
            enriquecidos[inbox.id] = await enrich_mercadopago_webhook_payload(
                db,
                store_id=inbox.store_id,
                payload=inbox.payload,
                configs=configs,
                persist_refresh=persistir,
            )
    return enriquecidos


async def _lock_appointment_or_skip(db: AsyncSession, payment: Payment) -> bool:
    """``FOR UPDATE SKIP LOCKED`` sobre el turno del cobro. False si otro lo tiene."""
    tomado = await db.execute(
        select(Appointment.id)
        .where(
            Appointment.id == payment.appointment_id,
            Appointment.store_id == payment.store_id,
        )
        .with_for_update(skip_locked=True)
    )
    return tomado.scalar_one_or_none() is not None


def _reconcilable_payments() -> Select[tuple[Payment]]:
    """Cobros de MP pendientes de una tienda con MP configurado."""
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
            PaymentGatewayConfig.provider == "mercadopago",
        )
    )


def _reconciliation_query(limit: int, now: datetime) -> Select[tuple[Payment]]:
    cutoff = now - timedelta(days=RECONCILIATION_LOOKBACK_DAYS)
    # Edad minima (F1-20, decision 20): un cobro recien creado es un cliente
    # que sigue en el checkout; preguntarle a MP por el gasta la corrida.
    min_age = now - timedelta(minutes=settings.RECONCILIATION_MIN_AGE_MINUTES)
    return (
        _reconcilable_payments()
        .where(Payment.created_at >= cutoff, Payment.created_at <= min_age)
        .order_by(Payment.created_at.asc())
        .limit(limit)
    )


async def reconcile_pending_payments(
    db: AsyncSession, *, limit: int = MP_BATCH_LIMIT
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


async def reconcile_one_payment(db: AsyncSession, payment_id: str) -> dict[str, int]:
    """Concilia UN cobro a pedido del poll publico (F1-21, decision 20).

    "Pague y sigue pendiente": el cliente volvio de MP y el webhook no llego o
    no se pudo aplicar. Mismas dos fases que la conciliacion general, sin su
    edad minima (el cliente ya dijo que pago) y sin su advisory lock: con el
    beat adentro no se saltearia, y la exclusion con el lote la dan los locks
    de fila (turno con SKIP LOCKED, despues el pago) y que la fase B solo
    toma el cobro si sigue pendiente. El pedido llega deduplicado por cobro
    (``modules/payments/on_demand.py``).
    """
    return await _reconcile(
        db, _reconcilable_payments().where(Payment.id == payment_id)
    )


async def _reconcile_pending_payments(
    db: AsyncSession, *, limit: int
) -> dict[str, int]:
    return await _reconcile(
        db, _reconciliation_query(limit, datetime.now(timezone.utc))
    )


async def _reconcile(
    db: AsyncSession, consulta: Select[tuple[Payment]]
) -> dict[str, int]:
    """Las mismas dos fases que el inbox (AUD2-B2-02, 2026-09-20).

    Aca el costo era el peor de los tres lotes: las filas bloqueadas son
    ``payments``, las mismas que toma ``find_payment_for_webhook`` en cada
    webhook entrante y ``get_by_appointment_locked`` al liberar un turno. Con
    ``lock_timeout = 5s`` en el rol de la app y MP lento, una corrida hacia
    fallar los webhooks y el boton "liberar turno" del panel.
    """
    pendientes = list((await db.execute(consulta)).scalars().all())
    # La configuracion es por tienda, no por cobro: una lectura con in_() antes
    # del for en vez de dos por cobro, una en la consulta a MP y otra en la
    # validacion de integridad (regla 12; 2026-09-20, AUD2-B2-06).
    configs, retiradas = await _lecturas_para_mp(db, pendientes)
    await AsyncSession.commit(db)
    remotos, fallidos, consultados = await _remote_payments_for_reconciliation(
        db, pendientes, configs, retiradas
    )
    await _apply_tenant_context(db)

    # Fase B SIN lock de lote: el orden unico de locks es turno -> pago
    # (F1-18, decision 23) y un ``FOR UPDATE ... OF payments`` sobre el lote
    # lo invertia (pago -> turno, el orden que F1-18 le saco al webhook). La
    # exclusion entre corridas ya la da el advisory lock (``_exclusive_job``);
    # la exclusion con un webhook o un "liberar" la dan los locks de fila que
    # se toman abajo, cobro por cobro y en orden.
    # Solo lo que la fase A consulto: un cobro que aparecio despues o que no
    # entro en el presupuesto no tiene respuesta de MP y lo toma la corrida
    # siguiente en vez de contarse como inspeccionado (F1-20).
    filas: list[Payment] = []
    if consultados:
        result = await db.execute(
            consulta.where(Payment.id.in_(consultados)).execution_options(
                populate_existing=True
            )
        )
        filas = list(result.scalars().all())
    conteo = {"reconciled": 0, "failed": fallidos, "inspected": 0}
    for payment in filas:
        resultado = await _conciliar_un_cobro(
            db, payment, remotos.get(payment.id), configs
        )
        for clave in resultado:
            conteo[clave] += 1

    await db.commit()
    return conteo


async def _conciliar_un_cobro(
    db: AsyncSession,
    payment: Payment,
    remote: dict[str, Any] | None,
    configs: GatewayConfigs,
) -> tuple[str, ...]:
    """Fase B de la conciliacion para UN cobro ya consultado: que contadores
    suma (``inspected``, ``reconciled``, ``failed``). Extraida de
    ``_reconcile`` por la regla 29 (revision de 3b977a9..6c84d46, #1)."""
    if not remote:
        # Sin respuesta de MP no hay nada que aplicar: tampoco se lockea.
        return ("inspected",)
    # ``reconciled`` cuenta cambios de estado reales, no no-ops (un pago
    # remoto que sigue pendiente; revision de e5579b6..3b977a9, #4 f).
    estado_previo = payment.status
    bloqueado = False
    try:
        # Savepoint por cobro (AUD2-B2-11): "no frenar al resto del lote"
        # no alcanzaba si la excepcion venia de la base, porque la
        # transaccion quedaba abortada y los cobros ya conciliados se
        # perdian en el commit final. Este lote no tiene attempts propio:
        # el cobro sigue pendiente y lo toma la corrida siguiente.
        async with db.begin_nested():
            # Primero el turno, con SKIP LOCKED: si un webhook o un
            # "liberar" lo tiene tomado, este cobro queda para la corrida
            # siguiente en vez de esperar (la semantica que antes daba el
            # SKIP LOCKED del lote de pagos). Despues el apply lockea el
            # pago, ya en el orden turno -> pago.
            if not await _lock_appointment_or_skip(db, payment):
                return ()
            bloqueado = True
            applied = await apply_mercadopago_webhook_payload(
                db,
                store_id=payment.store_id,
                payload={"data": remote, "status": remote.get("status")},
                configs=configs,
            )
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        # Como antes: cuenta como inspeccionado si ya habia tomado el turno.
        return ("inspected", "failed") if bloqueado else ("failed",)
    if applied and payment.status != estado_previo:
        return ("inspected", "reconciled")
    return ("inspected",)


async def _lecturas_para_mp(
    db: AsyncSession, pendientes: list[Payment]
) -> tuple[GatewayConfigs, dict[str, list[str]]]:
    """Lo que la fase A necesita leer ANTES de cerrar la transaccion: la config
    del gateway por tienda y las referencias de los links retirados de cada
    cobro (revision de perf/f4-pay). Dos consultas con in_() para el lote."""
    configs = await load_gateway_configs(db, (p.store_id for p in pendientes))
    return configs, await retired_link_references(db, pendientes)


async def _remote_payments_for_reconciliation(
    db: AsyncSession,
    pendientes: list[Payment],
    configs: GatewayConfigs,
    retiradas: Mapping[str, Sequence[str]],
) -> tuple[dict[str, dict[str, Any]], int, list[str]]:
    """{payment.id: pago remoto}, cuantos fallaron y cuales se consultaron.

    Corre en la fase A: sin lock y con la transaccion cerrada, y con el
    presupuesto de F1-20: lo que no entra no se consulta ni se cuenta.
    """
    persistir = partial(persist_gateway_refresh, db)
    remotos: dict[str, dict[str, Any]] = {}
    fallidos = 0
    consultados: list[str] = []
    limite = _reloj() + MP_PHASE_A_BUDGET_SECONDS
    for indice, payment in enumerate(pendientes):
        # Entre cobros y, adentro de ``_fetch_remote_payment``, antes de cada
        # consulta del mismo cobro.
        if _presupuesto_agotado(
            limite, job="reconciliation", sin_consultar=len(pendientes) - indice
        ):
            break
        try:
            remote = await _fetch_remote_payment(
                db,
                payment,
                configs,
                persistir,
                retiradas.get(payment.id, ()),
                limite=limite,
            )
        except _PresupuestoAgotado:
            _presupuesto_agotado(
                limite, job="reconciliation", sin_consultar=len(pendientes) - indice
            )
            break
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            fallidos += 1
            consultados.append(payment.id)
            continue
        consultados.append(payment.id)
        if remote:
            remotos[payment.id] = remote
    return remotos, fallidos, consultados


async def _fetch_remote_payment(
    db: AsyncSession,
    payment: Payment,
    configs: GatewayConfigs | None = None,
    persist_refresh: PersistRefresh | None = None,
    retiradas: Sequence[str] = (),
    *,
    limite: float | None = None,
) -> dict[str, Any] | None:
    """El pago de MP de este cobro: por id si lo tiene; si no, por la
    referencia del link vigente y, si ahi no hay uno acreditado, por las de
    sus links retirados en la ventana (``RETIRED_LINK_SEARCH_DAYS``): el
    webhook del pago de un link viejo pudo perderse.

    Como mucho ``RETIRED_LINK_SEARCH_MAX`` links retirados (los primeros de
    ``retiradas``, que viene del mas reciente al mas viejo) y el presupuesto
    ``limite`` se mira antes de CADA consulta: levanta ``_PresupuestoAgotado``
    aunque sea a mitad del cobro (revision de e5579b6..3b977a9, #1).

    Con id de MP, si ese pago no esta aprobado tambien se buscan los links
    retirados (revision #4 d): un rechazo sobre el link vigente no puede
    tapar un pago aprobado de un link viejo cuyo webhook se perdio.
    """
    primero: dict[str, Any] | None = None
    referencias: tuple[str, ...] = tuple(retiradas[:RETIRED_LINK_SEARCH_MAX])
    if payment.external_payment_id:
        _consultar_si_alcanza(limite)
        with mercadopago_budget(MP_QUERY_BUDGET_SECONDS):
            primero = await fetch_mercadopago_payment(
                db,
                store_id=payment.store_id,
                payment_id=payment.external_payment_id,
                configs=configs,
                persist_refresh=persist_refresh,
            )
        if primero is None or _es_aprobado(primero):
            return primero
    else:
        referencias = (payment.current_external_reference, *referencias)
    for referencia in referencias:
        _consultar_si_alcanza(limite)
        # Tope por consulta, refresh OAuth y reintento incluidos (#3).
        with mercadopago_budget(MP_QUERY_BUDGET_SECONDS):
            candidates = await search_mercadopago_payments(
                db,
                store_id=payment.store_id,
                external_reference=referencia,
                configs=configs,
                persist_refresh=persist_refresh,
            )
        # Un cobro acreditado gana; si no hay, el del id o el mas reciente
        # del vigente.
        for candidate in candidates:
            if _es_aprobado(candidate):
                return candidate
        if primero is None and candidates:
            primero = candidates[0]
    return primero


def _es_aprobado(remoto: Mapping[str, Any]) -> bool:
    return str(remoto.get("status") or "").lower() == "approved"


def _expired_holds_query(
    now: datetime, limit: int
) -> Select[tuple[Appointment, Payment]]:
    """Turnos con retencion vencida y sin cobro acreditado, los mas viejos primero.

    Sin cobro o con un cobro VIVO (``LIVE_CHARGE_PAYMENT_STATUSES``, unica
    fuente): desde la revision de perf/f4-pay (2026-09-25) tambien
    ``rejected``. Antes solo ``pending``: un turno pendiente cuyo link se
    rechazo no se liberaba nunca y el cliente tampoco podia cancelarlo.

    El job los vence por el grafo SIN publicar ``payment.preference.expire``:
    el link de MP se creo con ``expiration_date_to`` = la retencion
    (``prepare_mercadopago_preference``), asi que ya vencio solo; un PUT por
    retencion vencida solo sumaria carga a MP. Si el cobro ya estaba
    acreditado, el grafo no lo degrada.
    """
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
            or_(
                Payment.id.is_(None),
                Payment.status.in_(sorted(LIVE_CHARGE_PAYMENT_STATUSES)),
            ),
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
# El outbox conserva su SKIP LOCKED; el lock es del TICK del beat (cada 20 s):
# una sola corrida despachando mails a la vez (process_outbox_tick).
OUTBOX_JOB_LOCK = "job:process_payment_outbox"


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
    except SoftTimeLimitExceeded:
        # Cortado a mitad del unlock: la conexion no puede volver al pool con
        # el lock de sesion tomado.
        await conn.invalidate()
        raise
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


# Nombre publico para los jobs de otros modulos (retencion, F1-19): mismo
# lock de sesion y mismo namespace. Los de este modulo usan ``_exclusive_job``.
exclusive_job = _exclusive_job


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
    # mataba a mitad del job. Commit de AsyncSession y no de TenantSession (el
    # de TenantSession reabre otra transaccion); el contexto vuelve en fase B.
    configs, retiradas = await _lecturas_para_mp(db, pendientes)
    await AsyncSession.commit(db)
    remotos, consultados = await _fetch_remote_payments(
        pendientes,
        db=db,
        configs=configs,
        retiradas=retiradas,
        persist_refresh=partial(persist_gateway_refresh, db),
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
    expired, rescued, liberados = await _vencer_o_rescatar(
        db, rows, remotos, consultados
    )
    await db.commit()
    # El cupo vuelve a estar libre: la pagina publica no puede seguir
    # mostrandolo ocupado cinco minutos mas. Redis caido no frena el job.
    if liberados:
        try:
            cache = await get_availability_cache()
            for store_id, starts_at in liberados:
                await invalidate_availability(cache, store_id, starts_at)
        except REDIS_UNAVAILABLE_ERRORS as exc:
            # PV-22: solo el tipo; el texto de redis-py puede traer la URL
            # de conexion con la clave.
            logger.warning(
                "availability_cache_invalidation_failed",
                error_type=type(exc).__name__,
            )
    return {"expired": expired, "rescued": rescued, "inspected": len(rows)}


async def _vencer_o_rescatar(
    db: AsyncSession,
    rows: Sequence[Row[tuple[Appointment, Payment]]],
    remotos: Mapping[str, dict[str, Any]],
    consultados: set[str],
) -> tuple[int, int, list[tuple[str, datetime]]]:
    """Fase B del job de vencimiento, con los turnos bloqueados.

    Solo decide sobre los cobros de MP que la fase A consulto (``consultados``,
    tambien los que fallaron) y sobre los turnos sin cobro de MP. Uno que el
    presupuesto dejo sin consultar (revision de e5579b6..3b977a9, #1), o que
    la relectura con ``SKIP LOCKED`` trajo sin que la fase A lo viera (vencio
    mientras tanto o entro en el ``limit``; revision de 3b977a9..6c84d46,
    #2), no se vence en esta corrida: pudo estar pagado; lo decide la
    siguiente. Devuelve (vencidos, rescatados, (tienda, inicio) de cada turno
    liberado).
    """
    expired = 0
    rescued = 0
    liberados: list[tuple[str, datetime]] = []
    for appointment, payment in rows:
        if (
            payment is not None
            and payment.provider == "mercadopago"
            and payment.id not in consultados
        ):
            continue
        # Ultimo chequeo antes de liberar el turno: si el cobro se acredito y el
        # webhook nunca llego, vencerlo perderia una reserva ya pagada.
        if payment and await _apply_remote_payment(
            db, payment, remotos.get(payment.id)
        ):
            rescued += 1
            continue
        appointment.apply_status_transition(AppointmentStatus.EXPIRED)
        if payment:
            # Por el grafo (pending/rejected -> expired); sin vencer el link:
            # ver ``_expired_holds_query``.
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
    return expired, rescued, liberados


async def persist_gateway_refresh(
    db: AsyncSession, config: PaymentGatewayConfig
) -> None:
    """Persiste en el acto la config que un 401 hizo refrescar, en una
    transaccion corta propia, y la cierra antes de la siguiente llamada a MP.

    Publica desde AUD2-B2-08: la usa tambien el handler del webhook, que
    ahora consulta a MP con la transaccion del request cerrada y necesita la
    misma garantia (sin esto, ``refresh_mercadopago_oauth_connection`` cae al
    ``db.flush()`` por defecto y reabre la transaccion justo antes del
    segundo HTTP).

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
    retiradas: Mapping[str, Sequence[str]] | None = None,
    persist_refresh: PersistRefresh | None = None,
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Consulta a Mercado Pago los cobros pendientes: ({payment.id: pago
    remoto}, ids que se consultaron, aunque la consulta haya fallado).

    Se llama sin ningun lock tomado. Si la consulta de un cobro falla, no
    figura en el resultado y el turno vence: la conciliacion posterior va a
    detectar el cobro y dejarlo visible para reembolso. Con el mismo
    presupuesto que la conciliacion y el inbox (revision de e5579b6..3b977a9,
    #1: este job no tenia): lo que no se llego a consultar NO vence.
    """
    remotos: dict[str, dict[str, Any]] = {}
    consultados: set[str] = set()
    de_mp = [p for p in payments if p.provider == "mercadopago"]
    limite = _reloj() + MP_PHASE_A_BUDGET_SECONDS
    for indice, payment in enumerate(de_mp):
        if _presupuesto_agotado(
            limite, job="expire_holds", sin_consultar=len(de_mp) - indice
        ):
            return remotos, consultados
        try:
            remote = await _fetch_remote_payment(
                db,
                payment,
                configs,
                persist_refresh,
                (retiradas or {}).get(payment.id, ()),
                limite=limite,
            )
        except _PresupuestoAgotado:
            _presupuesto_agotado(
                limite, job="expire_holds", sin_consultar=len(de_mp) - indice
            )
            return remotos, consultados
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            # Consultado aunque haya fallado: el turno vence, como antes.
            consultados.add(payment.id)
            continue
        consultados.add(payment.id)
        if remote:
            remotos[payment.id] = remote
    return remotos, consultados


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
