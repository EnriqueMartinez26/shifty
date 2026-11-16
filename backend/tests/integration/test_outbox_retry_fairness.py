"""Regresiones de equidad, cuotas y reintentos durables del despacho SMTP."""

from __future__ import annotations

import smtplib
from datetime import datetime, time, timedelta, timezone
from email.message import EmailMessage
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import mail_budget
from core.config import settings
import modules.notifications.tasks as notification_tasks
import modules.payments.jobs as jobs
from modules.payments.model import OUTBOX_EMAIL_MAX_ATTEMPTS, OutboxMessage
from core.mail_budget import mail_delivery_context
from tests.redis_mail_budget_double import AtomicMailBudgetRedis


class _Reloj:
    def __init__(self, now: datetime) -> None:
        self.now = now


class _DateTimeCongelado(datetime):
    reloj: _Reloj

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        if tz is None:
            return cls.reloj.now.replace(tzinfo=None)
        return cls.reloj.now.astimezone(tz)


class _Smtp450UnaVez:
    """Fake the SMTP boundary while preserving a real pre-DATA 450 reply."""

    def __init__(
        self,
        destinatario_temporal: str,
        *,
        respuesta_ambigua_despues_de_data: bool = False,
    ) -> None:
        self.destinatario_temporal = destinatario_temporal
        self.rechazo_emitido = False
        self.respuesta_ambigua_despues_de_data = respuesta_ambigua_despues_de_data
        self.intentos_smtp = 0
        self.entregados: list[str] = []

    def starttls(self, **_kwargs: Any) -> None:
        return None

    def login(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def noop(self) -> tuple[int, bytes]:
        return 250, b"OK"

    def send_message(self, message: EmailMessage) -> None:
        self.intentos_smtp += 1
        destinatario = str(message["To"])
        if self.respuesta_ambigua_despues_de_data:
            self.data(message.as_bytes())
        if destinatario == self.destinatario_temporal and not self.rechazo_emitido:
            self.rechazo_emitido = True
            raise smtplib.SMTPRecipientsRefused(
                {destinatario: (450, b"4.2.0 try again later")}
            )
        self.data(message.as_bytes())
        self.deliveries.append(destinatario)

    def data(self, _message: bytes | str) -> tuple[int, bytes]:
        if self.respuesta_ambigua_despues_de_data:
            self.respuesta_ambigua_despues_de_data = False
            raise smtplib.SMTPServerDisconnected("lost response after DATA")
        return 250, b"accepted"

    @property
    def deliveries(self) -> list[str]:
        return self.entregados

    def quit(self) -> tuple[int, bytes]:
        return 221, b"bye"

    def close(self) -> None:
        return None


def _mail(destinatario: str, *, prioridad: str | None = None) -> OutboxMessage:
    detalles = {
        "public_id": f"turno-{destinatario.split('@', 1)[0]}",
        "client_name": "Cliente de prueba",
        "service": "Consulta",
    }
    payload: dict[str, Any] = {
        "mail": "cancellation",
        "args": {"email": destinatario, "details": detalles},
        "logical_id": f"cancel:{detalles['public_id']}",
    }
    if prioridad is not None:
        payload["priority"] = prioridad
    return OutboxMessage(
        store_id="tienda-outbox-retry-fairness",
        event_type=jobs.EVENT_EMAIL_SEND,
        payload=payload,
        delivery_status="pending",
    )


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _send_with_smtp(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    rows: list[OutboxMessage],
    smtp: _Smtp450UnaVez,
) -> None:
    session.add_all(rows)
    await session.commit()
    monkeypatch.setattr(notification_tasks.smtplib, "SMTP", lambda *_a, **_k: smtp)
    await jobs._dispatch_pending_emails(session)


async def _reload_rows(
    session: AsyncSession,
) -> list[OutboxMessage]:
    await session.flush()
    return list(
        (
            await session.execute(
                select(OutboxMessage)
                .where(OutboxMessage.event_type == jobs.EVENT_EMAIL_SEND)
                .order_by(OutboxMessage.created_at.asc())
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


def _rows_by_email(rows: list[OutboxMessage]) -> dict[str, OutboxMessage]:
    return {
        str(row.payload["args"]["email"]): row
        for row in rows
        if isinstance(row.payload, dict) and isinstance(row.payload.get("args"), dict)
    }


@pytest.mark.asyncio
async def test_un_450_no_bloquea_diez_mails_entregables_en_el_mismo_dispatch(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    destinatarios = [f"cliente-{indice}@example.com" for indice in range(11)]
    smtp = _Smtp450UnaVez(destinatarios[0])

    await _send_with_smtp(
        test_session,
        monkeypatch,
        [_mail(destinatario) for destinatario in destinatarios],
        smtp,
    )

    assert smtp.deliveries == destinatarios[1:], (
        "un 450 pre-DATA debe reprogramar solo esa fila y dejar avanzar las otras diez"
    )
    rows = _rows_by_email(await _reload_rows(test_session))
    assert rows[destinatarios[0]].delivery_status == "pending"
    assert rows[destinatarios[0]].attempts == 1
    assert rows[destinatarios[0]].next_attempt_at is not None
    assert all(rows[email].delivery_status == "sent" for email in destinatarios[1:])
    assert all(rows[email].attempts == 1 for email in destinatarios[1:])


@pytest.mark.asyncio
async def test_el_dispatch_respeta_el_tope_de_cien_filas(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_limit = jobs.OUTBOX_EMAIL_MAX_PER_DISPATCH
    assert configured_limit == 100
    monkeypatch.setattr(jobs, "OUTBOX_EMAIL_MAX_PER_DISPATCH", 2)
    destinatarios = [f"lote-{indice}@example.com" for indice in range(3)]
    smtp = _Smtp450UnaVez("nunca-se-rechaza@example.com")

    await _send_with_smtp(
        test_session,
        monkeypatch,
        [_mail(destinatario) for destinatario in destinatarios],
        smtp,
    )

    rows = _rows_by_email(await _reload_rows(test_session))
    assert len(smtp.deliveries) == 2
    assert sum(row.delivery_status == "sent" for row in rows.values()) == 2
    assert all(
        row.attempts == 1 for row in rows.values() if row.delivery_status == "sent"
    )
    assert rows[destinatarios[2]].delivery_status == "pending"


@pytest.mark.asyncio
async def test_un_mail_diferido_por_presupuesto_no_bloquea_uno_critico_y_espera_el_reset(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 1)
    monkeypatch.setattr(settings, "MAIL_CRITICAL_RESERVE_PERCENT", 100)
    monkeypatch.setattr(settings, "MAIL_BUDGET_TIMEZONE", "UTC")
    monkeypatch.setattr(settings, "MAIL_BUDGET_RESET_HOUR", 0)
    redis = AtomicMailBudgetRedis()

    async def get_redis() -> AtomicMailBudgetRedis:
        return redis

    monkeypatch.setattr(mail_budget, "get_redis", get_redis)
    ahora = _now_utc()
    reloj = _Reloj(ahora)
    _DateTimeCongelado.reloj = reloj
    monkeypatch.setattr(jobs, "datetime", _DateTimeCongelado)
    monkeypatch.setattr(mail_budget, "datetime", _DateTimeCongelado)
    reset = datetime.combine(
        (ahora + timedelta(days=1)).date(), time.min, tzinfo=timezone.utc
    )
    smtp = _Smtp450UnaVez("no-se-rechaza@example.com")
    medium = _mail("medium@example.com", prioridad="medium")
    invalid_priority = _mail("invalid-priority@example.com", prioridad="critcal")
    critical = _mail("critical@example.com", prioridad="critical")
    medium.created_at = ahora
    invalid_priority.created_at = ahora + timedelta(microseconds=1)
    critical.created_at = ahora + timedelta(microseconds=2)

    await _send_with_smtp(
        test_session, monkeypatch, [medium, invalid_priority, critical], smtp
    )

    assert smtp.deliveries == ["critical@example.com"], (
        "la denegación de cuota para medium no debe cortar el despacho del correo crítico"
    )
    rows = _rows_by_email(await _reload_rows(test_session))
    assert rows["medium@example.com"].delivery_status == "pending"
    assert rows["medium@example.com"].attempts == 0
    assert _as_utc(rows["medium@example.com"].next_attempt_at) == reset
    assert rows["invalid-priority@example.com"].delivery_status == "pending"
    assert rows["invalid-priority@example.com"].attempts == 0
    assert _as_utc(rows["invalid-priority@example.com"].next_attempt_at) == reset
    assert rows["critical@example.com"].delivery_status == "sent"


@pytest.mark.asyncio
async def test_fallo_450_persiste_backoff_y_se_reintenta_solo_al_vencer(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ahora = _now_utc()
    reloj = _Reloj(ahora)
    _DateTimeCongelado.reloj = reloj
    monkeypatch.setattr(jobs, "datetime", _DateTimeCongelado)
    destinatario = "reintento@example.com"
    smtp = _Smtp450UnaVez(destinatario)
    row = _mail(destinatario)

    await _send_with_smtp(test_session, monkeypatch, [row], smtp)

    await test_session.refresh(row)
    due_at = _as_utc(row.next_attempt_at)
    assert row.delivery_status == "pending"
    assert row.attempts == 1
    assert due_at == ahora + timedelta(seconds=20)

    # A committed/reloaded row must remain unavailable before its retry time.
    test_session.expunge_all()
    row = (
        await test_session.execute(
            select(OutboxMessage).where(OutboxMessage.id == row.id)
        )
    ).scalar_one()
    reloj.now = due_at - timedelta(microseconds=1)
    await jobs._dispatch_pending_emails(test_session)
    await test_session.refresh(row)
    assert smtp.deliveries == []
    assert row.attempts == 1

    reloj.now = due_at
    await jobs._dispatch_pending_emails(test_session)
    await test_session.refresh(row)
    assert smtp.deliveries == [destinatario]
    assert row.delivery_status == "sent"
    assert row.attempts == 2


@pytest.mark.asyncio
async def test_el_mail_agota_el_maximo_de_intentos_y_queda_terminal(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ahora = _now_utc()
    reloj = _Reloj(ahora)
    _DateTimeCongelado.reloj = reloj
    monkeypatch.setattr(jobs, "datetime", _DateTimeCongelado)
    destinatario = "siempre-450@example.com"
    row = _mail(destinatario)
    avisos_de_agotamiento: list[dict[str, Any]] = []
    avisos_del_sink: list[dict[str, Any]] = []
    monkeypatch.setattr(
        jobs,
        "report_mail_failure",
        lambda **context: avisos_de_agotamiento.append(context),
    )
    monkeypatch.setattr(
        notification_tasks,
        "report_mail_failure",
        lambda **context: avisos_del_sink.append(context),
    )

    # Every dispatch receives a fresh transient 450; advance to the durable
    # retry time each time so this exercises the attempt ceiling, not a busy loop.
    def new_smtp_session(*_args: Any, **_kwargs: Any) -> _Smtp450UnaVez:
        return _Smtp450UnaVez(destinatario)

    monkeypatch.setattr(notification_tasks.smtplib, "SMTP", new_smtp_session)
    test_session.add(row)
    await test_session.commit()
    retrasos: list[float] = []
    for _attempt in range(OUTBOX_EMAIL_MAX_ATTEMPTS):
        await jobs._dispatch_pending_emails(test_session)
        await test_session.refresh(row)
        if row.next_attempt_at is not None:
            retry_at = _as_utc(row.next_attempt_at)
            retrasos.append((retry_at - reloj.now).total_seconds())
            reloj.now = retry_at

    await test_session.refresh(row)
    assert row.attempts == OUTBOX_EMAIL_MAX_ATTEMPTS
    assert row.delivery_status == "failed"
    assert row.error
    assert retrasos == [20, 40, 80, 160, 300, 300, 300, 300, 300]
    assert len(avisos_de_agotamiento) == 1
    assert avisos_de_agotamiento[0].get("recipient") is None
    assert avisos_del_sink == []
    assert destinatario not in repr(avisos_de_agotamiento)
    await jobs._dispatch_pending_emails(test_session)
    assert row.attempts == OUTBOX_EMAIL_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_resultado_ambiguo_despues_de_data_queda_unknown_y_no_se_reenvia(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    destinatario = "ambiguo@example.com"
    smtp = _Smtp450UnaVez(
        destinatario,
        respuesta_ambigua_despues_de_data=True,
    )
    row = _mail(destinatario)

    await _send_with_smtp(test_session, monkeypatch, [row], smtp)
    await test_session.refresh(row)

    assert row.delivery_status == "unknown"
    assert smtp.intentos_smtp == 1
    await jobs._dispatch_pending_emails(test_session)
    await test_session.refresh(row)
    assert row.delivery_status == "unknown"
    assert smtp.intentos_smtp == 1


@pytest.mark.asyncio
async def test_redis_no_disponible_difiere_sesenta_segundos_sin_gastar_intento_ni_bloquear(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 250)
    monkeypatch.setattr(settings, "MAIL_CRITICAL_RESERVE_PERCENT", 20)
    monkeypatch.setattr(settings, "MAIL_BUDGET_TIMEZONE", "UTC")
    monkeypatch.setattr(settings, "MAIL_BUDGET_RESET_HOUR", 0)
    ahora = _now_utc()
    reloj = _Reloj(ahora)
    _DateTimeCongelado.reloj = reloj
    monkeypatch.setattr(jobs, "datetime", _DateTimeCongelado)
    redis = AtomicMailBudgetRedis()
    fallas_temporales = 2

    async def get_redis() -> Any:
        nonlocal fallas_temporales
        if fallas_temporales:
            fallas_temporales -= 1
            raise ConnectionError("redis unavailable")
        return redis

    monkeypatch.setattr(mail_budget, "get_redis", get_redis)
    temporal = _mail("redis-temporal@example.com", prioridad="medium")
    critical = _mail("redis-available@example.com", prioridad="critical")
    smtp = _Smtp450UnaVez("no-se-rechaza@example.com")

    await _send_with_smtp(test_session, monkeypatch, [temporal, critical], smtp)

    assert smtp.deliveries == ["redis-available@example.com"], (
        "una denegación de cuota por Redis debe liberar esa fila y seguir con la cola"
    )
    rows = _rows_by_email(await _reload_rows(test_session))
    assert rows["redis-temporal@example.com"].delivery_status == "pending"
    assert rows["redis-temporal@example.com"].attempts == 0
    assert _as_utc(rows["redis-temporal@example.com"].next_attempt_at) == (
        ahora + timedelta(seconds=60)
    )
    assert rows["redis-available@example.com"].delivery_status == "sent"


@pytest.mark.asyncio
async def test_smtp_450_pre_data_es_retryable_y_no_ambiguo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destinatario = "450@example.com"
    smtp_fake = _Smtp450UnaVez(destinatario)
    smtp = notification_tasks.SmtpSession()
    monkeypatch.setattr(smtp, "_connect", lambda: smtp_fake)

    with mail_delivery_context(
        priority="high",
        message_id="smtp-450-pre-data",
        retry_pre_data=True,
    ):
        delivered = await smtp.send(destinatario, "Asunto", "Cuerpo")

    assert delivered is False
    assert smtp.last_delivery_attempted is True
    assert smtp.last_delivery_retryable is True
    assert smtp.last_delivery_ambiguous is False
    smtp.close()
