from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta, timezone
import smtplib
from types import SimpleNamespace
from typing import Any

import pytest

from core import mail_budget
from core.config import settings
from core.mail_budget import (
    MailPriority,
    MailReservation,
    current_mail_context,
    current_mail_pre_data_retry,
    current_mail_reserved_retry,
)
from modules.payments import jobs
from modules.payments.model import WEBHOOK_INBOX_MAX_ATTEMPTS
from modules.notifications import tasks
from tests.redis_mail_budget_double import AtomicMailBudgetRedis

_CLIENT_MAIL_BUILDERS = {
    "cancellation": ("_cancellation_subject", "_cancellation_body"),
    "confirmation": ("_confirmation_subject", "_confirmation_body"),
    "reminder": ("_reminder_subject", "_reminder_body"),
    "rebook": ("_rebook_subject", "_rebook_body"),
    "reschedule": ("_rescheduled_subject", "_rescheduled_body"),
    "waitlist_offer": ("_waitlist_offer_subject", "_waitlist_offer_body"),
}


class _OutboxMailRow:
    def __init__(self) -> None:
        self.id = "outbox-retry-1"
        self.store_id = "store-1"
        self.event_type = "email.send"
        self.payload = {"mail": "confirmation", "args": {"to": "client@example.com"}}
        self.processed_at: datetime | None = None
        self.attempts = 0
        self.error: str | None = None

    def register_failure(self, reason: str) -> None:
        self.attempts += 1
        self.error = reason
        if self.attempts >= WEBHOOK_INBOX_MAX_ATTEMPTS:
            self.processed_at = datetime.now(timezone.utc)


class _ScriptedSMTP:
    def __init__(self, outcome: str | Exception) -> None:
        self.outcome = outcome
        self.send_message_calls = 0
        self.data_calls = 0

    def send_message(self, _message: Any) -> None:
        self.send_message_calls += 1
        if self.outcome == "connection-before-data":
            raise ConnectionError("connection lost before DATA")
        if self.outcome == "4xx-before-data":
            raise smtplib.SMTPResponseException(451, b"try again later")
        self.data(b"message body")
        if isinstance(self.outcome, Exception):
            raise self.outcome

    def data(self, _message: bytes | str) -> tuple[int, bytes]:
        self.data_calls += 1
        return 250, b"accepted"

    def close(self) -> None:
        return None

    def quit(self) -> tuple[int, bytes]:
        return 221, b"bye"


def _wire_outbox_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    row: _OutboxMailRow,
    smtp_factory: Callable[[], _ScriptedSMTP],
    *,
    use_real_sender: bool = False,
    real_sender_kind: str = "confirmation",
) -> list[_ScriptedSMTP]:
    connections: list[_ScriptedSMTP] = []
    monkeypatch.setattr(settings, "MAIL_BUDGET_TIMEZONE", "UTC")
    monkeypatch.setattr(settings, "MAIL_BUDGET_RESET_HOUR", 0)

    async def claim(*_args: Any, **_kwargs: Any) -> Any:
        if row.processed_at is not None:
            return None
        row.processed_at = datetime.now(timezone.utc)
        return row

    async def apply_context(_db: Any) -> None:
        return None

    async def commit(_db: Any) -> None:
        return None

    @asynccontextmanager
    async def smtp_session() -> AsyncIterator[tasks.SmtpSession]:
        session = tasks.SmtpSession()

        def connect() -> _ScriptedSMTP:
            connection = smtp_factory()
            connections.append(connection)
            return connection

        monkeypatch.setattr(session, "_connect", connect)
        try:
            yield session
        finally:
            session.close()

    async def send(*, smtp: tasks.SmtpSession, to: str) -> dict[str, str]:
        delivered = await smtp.send(to, "Subject", "Body")
        return {"status": "sent" if delivered else "failed", "reason": "smtp"}

    if use_real_sender:
        if real_sender_kind == "store_notification":
            row.payload = {
                "mail": real_sender_kind,
                "args": {
                    "email": "store@example.com",
                    "title": "New appointment",
                    "body": "A client booked a time.",
                },
            }
        else:
            builders = _CLIENT_MAIL_BUILDERS.get(real_sender_kind)
            if builders is None:
                raise AssertionError(f"unknown real sender kind: {real_sender_kind}")
            details = {"public_id": "appointment-1"}
            if real_sender_kind == "reminder":
                details["stage"] = "24h"
            row.payload = {
                "mail": real_sender_kind,
                "args": {
                    "email": "client@example.com",
                    "details": details,
                },
            }
            if real_sender_kind == "reminder":
                row.payload["logical_id"] = "reminder:appointment-1:24h"
                row.payload["expires_at"] = (
                    datetime.now(timezone.utc) + timedelta(hours=1)
                ).isoformat()
            monkeypatch.setattr(tasks, builders[0], lambda _details: "Subject")
            monkeypatch.setattr(tasks, builders[1], lambda _details: "Body")

    monkeypatch.setattr(jobs, "_claim_next_email", claim)
    monkeypatch.setattr(jobs, "_apply_tenant_context", apply_context)
    monkeypatch.setattr(jobs, "smtp_session", smtp_session)
    if not use_real_sender:
        monkeypatch.setattr(jobs, "_sender", lambda _kind: send)
    monkeypatch.setattr("modules.payments.jobs.AsyncSession.commit", commit)
    return connections


@pytest.mark.parametrize("decision", ["deferred", "unavailable"])
@pytest.mark.asyncio
async def test_outbox_difiere_sin_consumir_intento_y_libera_el_reclamo(
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
) -> None:
    fila = SimpleNamespace(
        processed_at=datetime.now(timezone.utc),
        attempts=0,
        payload={"appointment_id": "appointment-1"},
        event_type="email.send",
        store_id="store-1",
    )
    commits: list[object] = []
    reclamos = 0

    async def claim(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal reclamos
        reclamos += 1
        return fila if reclamos == 1 else None

    async def deferred(_fila: Any, smtp: Any) -> str:
        smtp.last_budget_decision = decision
        return "budget"

    async def apply_context(_db: Any) -> None:
        return None

    async def commit(db: Any) -> None:
        commits.append(db)

    class Smtp:
        last_budget_decision: str | None = None

    smtp = Smtp()

    @asynccontextmanager
    async def smtp_session() -> AsyncIterator[Smtp]:
        yield smtp

    monkeypatch.setattr(jobs, "_claim_next_email", claim)
    monkeypatch.setattr(jobs, "_send_one_pending_email", deferred)
    monkeypatch.setattr(jobs, "_apply_tenant_context", apply_context)
    monkeypatch.setattr(jobs, "smtp_session", smtp_session)
    monkeypatch.setattr("modules.payments.jobs.AsyncSession.commit", commit)

    db = object()
    await jobs._dispatch_pending_emails(db)  # type: ignore[arg-type]

    assert fila.processed_at is None
    assert fila.attempts == 0
    assert commits == [db]
    assert reclamos == 1


@pytest.mark.asyncio
async def test_outbox_descarta_baja_prioridad_sin_contarla_como_fallo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fila = SimpleNamespace(
        processed_at=datetime.now(timezone.utc),
        attempts=0,
        payload={"appointment_id": "appointment-1"},
        event_type="email.send",
        store_id="store-1",
    )
    reclamos = 0

    async def claim(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal reclamos
        reclamos += 1
        return fila if reclamos == 1 else None

    async def dropped(_fila: Any, smtp: Any) -> str:
        smtp.last_budget_decision = "dropped"
        return "budget"

    class Smtp:
        last_budget_decision: str | None = None

    smtp = Smtp()

    @asynccontextmanager
    async def smtp_session() -> AsyncIterator[Smtp]:
        yield smtp

    monkeypatch.setattr(jobs, "_claim_next_email", claim)
    monkeypatch.setattr(jobs, "_send_one_pending_email", dropped)
    monkeypatch.setattr(jobs, "smtp_session", smtp_session)

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]

    assert fila.processed_at is not None
    assert fila.attempts == 0
    assert reclamos == 2


@pytest.mark.parametrize(
    ("mail_kind", "expected_priority"),
    [("rebook", "low"), ("confirmation", "high"), ("reminder", "medium")],
)
@pytest.mark.asyncio
async def test_outbox_asigna_prioridad_y_clave_estables_por_fila(
    monkeypatch: pytest.MonkeyPatch,
    mail_kind: str,
    expected_priority: str,
) -> None:
    contexts: list[tuple[str, str] | None] = []
    fila = SimpleNamespace(
        id=123,
        store_id="store-1",
        event_type="email.send",
        payload={"mail": mail_kind, "args": {"email": "client@example.com"}},
    )
    expected_message_id = "outbox:123"
    if mail_kind == "reminder":
        fila.payload = {
            "mail": "reminder",
            "args": {
                "email": "client@example.com",
                "details": {"public_id": "appointment-1", "stage": "24h"},
            },
            "logical_id": "reminder:appointment-1:24h",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
        expected_message_id = "reminder:appointment-1:24h"
        monkeypatch.setattr(tasks, "_reminder_subject", lambda _details: "Subject")
        monkeypatch.setattr(tasks, "_reminder_body", lambda _details: "Body")

    async def send(**_kwargs: Any) -> dict[str, str]:
        contexts.append(current_mail_context())
        return {"status": "sent"}

    monkeypatch.setattr(jobs, "_sender", lambda _kind: send)

    assert await jobs._send_one_pending_email(fila, object()) is None  # type: ignore[arg-type]
    assert contexts == [(expected_priority, expected_message_id)]
    assert current_mail_context() is None


@pytest.mark.asyncio
async def test_recordatorio_vencido_queda_terminal_sin_intentar_smtp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _OutboxMailRow()
    connections = _wire_outbox_dispatch(
        monkeypatch,
        row,
        lambda: _ScriptedSMTP("success"),
        use_real_sender=True,
        real_sender_kind="reminder",
    )
    row.payload["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    first_terminal_at = row.processed_at
    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]

    assert first_terminal_at is not None
    assert row.processed_at == first_terminal_at
    assert row.error == "reminder_expired"
    assert row.attempts == 0
    assert connections == []


@pytest.mark.asyncio
async def test_crash_despues_del_claim_no_reenvia_recordatorio_ambiguo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _OutboxMailRow()
    connections = _wire_outbox_dispatch(
        monkeypatch,
        row,
        lambda: _ScriptedSMTP("success"),
        use_real_sender=True,
        real_sender_kind="reminder",
    )

    async def worker_interrupted(_row: Any, _smtp: Any) -> None:
        raise tasks.SoftTimeLimitExceeded()

    monkeypatch.setattr(jobs, "_send_one_pending_email", worker_interrupted)
    with pytest.raises(tasks.SoftTimeLimitExceeded):
        await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    claim_time = row.processed_at

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]

    assert claim_time is not None
    assert row.processed_at == claim_time
    assert row.attempts == 0
    assert connections == []


@pytest.mark.parametrize("decision", ["deferred", "unavailable"])
@pytest.mark.asyncio
async def test_recordatorio_deferido_por_budget_sigue_pendiente_en_outbox(
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    row = _OutboxMailRow()
    connections = _wire_outbox_dispatch(
        monkeypatch,
        row,
        lambda: _ScriptedSMTP("success"),
        use_real_sender=True,
        real_sender_kind="reminder",
    )

    async def reserve(**kwargs: Any) -> MailReservation:
        assert kwargs == {
            "priority": "medium",
            "message_id": "reminder:appointment-1:24h",
        }
        return MailReservation(
            decision=decision,  # type: ignore[arg-type]
            window_id="test-window",
            message_key="message",
            attempt_token="attempt",
            priority="medium",
        )

    monkeypatch.setattr(tasks, "reserve_mail", reserve)
    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]

    assert row.processed_at is None
    assert row.attempts == 0
    assert connections == []


@pytest.mark.asyncio
async def test_recordatorio_preserva_fila_si_redis_falla_con_cap_activo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    monkeypatch.setattr(mail_budget, "report_mail_failure", lambda **_kwargs: None)
    row = _OutboxMailRow()
    connections = _wire_outbox_dispatch(
        monkeypatch,
        row,
        lambda: _ScriptedSMTP("success"),
        use_real_sender=True,
        real_sender_kind="reminder",
    )
    redis_attempts = 0

    async def unavailable() -> None:
        nonlocal redis_attempts
        redis_attempts += 1
        raise OSError("redis unavailable")

    monkeypatch.setattr(mail_budget, "get_redis", unavailable)
    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]

    assert redis_attempts == mail_budget._REDIS_RETRIES
    assert row.processed_at is None
    assert row.attempts == 0
    assert connections == []


@pytest.mark.asyncio
async def test_recordatorio_no_se_bloquea_si_el_budget_esta_desactivado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", None)
    row = _OutboxMailRow()
    connections = _wire_outbox_dispatch(
        monkeypatch,
        row,
        lambda: _ScriptedSMTP("success"),
        use_real_sender=True,
        real_sender_kind="reminder",
    )

    async def unavailable() -> None:
        raise OSError("redis unavailable")

    monkeypatch.setattr(mail_budget, "get_redis", unavailable)
    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]

    assert row.processed_at is not None
    assert row.attempts == 0
    assert len(connections) == 1
    assert connections[0].data_calls == 1


@pytest.mark.asyncio
async def test_recordatorio_al_limite_de_presupuesto_sigue_pendiente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    monkeypatch.setattr(settings, "MAIL_CRITICAL_RESERVE_PERCENT", 20)
    monkeypatch.setattr(mail_budget, "_window", lambda now=None: ("test-window", 3600))
    redis = AtomicMailBudgetRedis()

    async def get_redis() -> AtomicMailBudgetRedis:
        return redis

    monkeypatch.setattr(mail_budget, "get_redis", get_redis)
    for index in range(4):
        reservation = await mail_budget.reserve_mail(
            priority="high", message_id=f"seed:{index}"
        )
        assert reservation.decision == "admitted"

    row = _OutboxMailRow()
    connections = _wire_outbox_dispatch(
        monkeypatch,
        row,
        lambda: _ScriptedSMTP("success"),
        use_real_sender=True,
        real_sender_kind="reminder",
    )
    # _wire_outbox_dispatch leaves the real reservation function installed.
    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]

    assert row.processed_at is None
    assert row.attempts == 0
    assert connections == []
    metrics = await mail_budget.read_mail_budget_metrics()
    assert metrics["admitted"] == 4
    assert metrics["deferred"] == 1


@pytest.mark.asyncio
async def test_recordatorio_reintenta_fallo_transitorio_antes_de_data_con_mismo_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un fallo pre-DATA reabre el recordatorio y reutiliza su cupo."""
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    redis = AtomicMailBudgetRedis()

    async def get_redis() -> AtomicMailBudgetRedis:
        return redis

    monkeypatch.setattr(mail_budget, "get_redis", get_redis)
    monkeypatch.setattr(mail_budget, "_window", lambda now=None: ("test-window", 3600))
    monkeypatch.setattr(mail_budget, "report_mail_failure", lambda **_kwargs: None)
    row = _OutboxMailRow()
    outcomes = iter(["connection-before-data", "success"])
    connections = _wire_outbox_dispatch(
        monkeypatch,
        row,
        lambda: _ScriptedSMTP(next(outcomes)),
        use_real_sender=True,
        real_sender_kind="reminder",
    )
    original_reserve_mail = mail_budget.reserve_mail
    reservations: list[tuple[MailPriority, str, bool]] = []

    async def record_reserve_mail(
        *, priority: MailPriority, message_id: str
    ) -> MailReservation:
        reservations.append((priority, message_id, current_mail_pre_data_retry()))
        return await original_reserve_mail(priority=priority, message_id=message_id)

    monkeypatch.setattr(tasks, "reserve_mail", record_reserve_mail)

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    assert row.processed_at is None
    assert row.attempts == 1
    assert connections[0].data_calls == 0

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    metrics = await mail_budget.read_mail_budget_metrics()

    assert row.processed_at is not None
    assert [reservation[0] for reservation in reservations] == ["medium", "medium"]
    assert [reservation[1] for reservation in reservations] == [
        "reminder:appointment-1:24h",
        "reminder:appointment-1:24h",
    ]
    assert [reservation[2] for reservation in reservations] == [True, True]
    assert [connection.data_calls for connection in connections] == [0, 1]
    assert metrics["admitted"] == 1
    assert metrics["failed"] == 1
    assert metrics["sent"] == 1


@pytest.mark.asyncio
async def test_recordatorio_duplicado_usa_id_logico_y_no_reenvia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    monkeypatch.setattr(mail_budget, "_window", lambda now=None: ("test-window", 3600))
    redis = AtomicMailBudgetRedis()

    async def get_redis() -> AtomicMailBudgetRedis:
        return redis

    monkeypatch.setattr(mail_budget, "get_redis", get_redis)
    monkeypatch.setattr(mail_budget, "report_mail_failure", lambda **_kwargs: None)
    row = _OutboxMailRow()
    connections = _wire_outbox_dispatch(
        monkeypatch,
        row,
        lambda: _ScriptedSMTP("success"),
        use_real_sender=True,
        real_sender_kind="reminder",
    )

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    row.processed_at = None  # simulate a duplicate SQL dispatch of the same row
    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    metrics = await mail_budget.read_mail_budget_metrics()

    assert row.processed_at is not None
    assert row.attempts == 1
    assert len(connections) == 1
    assert connections[0].data_calls == 1
    assert metrics["admitted"] == 1
    assert metrics["sent"] == 1


def test_cada_reoferta_de_lista_de_espera_tiene_idempotencia_propia() -> None:
    primera = {
        "public_id": "entry-1",
        "starts_at": "2026-11-14T15:00:00+00:00",
    }
    segunda = {
        "public_id": "entry-1",
        "starts_at": "2026-11-15T15:00:00+00:00",
    }

    assert tasks._mail_message_id("waitlist-offer", primera) == tasks._mail_message_id(
        "waitlist-offer", primera
    )
    assert tasks._mail_message_id("waitlist-offer", primera) != tasks._mail_message_id(
        "waitlist-offer", segunda
    )


@pytest.mark.parametrize(
    ("real_sender_kind", "expected_priority"),
    [
        ("cancellation", "high"),
        ("confirmation", "high"),
        ("rebook", "low"),
        ("reschedule", "high"),
        ("store_notification", "high"),
        ("waitlist_offer", "high"),
    ],
)
@pytest.mark.parametrize("first_outcome", ["connection-before-data", "4xx-before-data"])
@pytest.mark.asyncio
async def test_outbox_reintenta_fallo_pre_data_con_mismo_id_y_un_solo_cupo(
    monkeypatch: pytest.MonkeyPatch,
    first_outcome: str,
    real_sender_kind: str,
    expected_priority: MailPriority,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    row = _OutboxMailRow()
    outcomes = iter([first_outcome, "success"])
    connections = _wire_outbox_dispatch(
        monkeypatch,
        row,
        lambda: _ScriptedSMTP(next(outcomes)),
        use_real_sender=True,
        real_sender_kind=real_sender_kind,
    )
    original_reserve_mail = mail_budget.reserve_mail
    reservations: list[tuple[MailPriority, str, bool]] = []

    async def record_reserve_mail(
        *, priority: MailPriority, message_id: str
    ) -> MailReservation:
        reservations.append((priority, message_id, current_mail_pre_data_retry()))
        return await original_reserve_mail(priority=priority, message_id=message_id)

    monkeypatch.setattr(tasks, "reserve_mail", record_reserve_mail)

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    assert row.attempts == 1
    assert row.processed_at is None
    assert connections[0].data_calls == 0

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    metrics = await mail_budget.read_mail_budget_metrics()

    assert row.processed_at is not None
    assert len(connections) == 2
    assert [connection.send_message_calls for connection in connections] == [1, 1]
    assert [connection.data_calls for connection in connections] == [0, 1]
    assert metrics["admitted"] == 1
    assert metrics[f"priority:{expected_priority}"] == 1
    assert metrics["failed"] == 1
    assert metrics["sent"] == 1
    assert reservations == [
        (expected_priority, "outbox:outbox-retry-1", True),
        (expected_priority, "outbox:outbox-retry-1", True),
    ]


@pytest.mark.asyncio
async def test_outbox_recupera_reserva_si_redis_falla_al_registrar_fallo_pre_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    row = _OutboxMailRow()
    outcomes = iter(["connection-before-data", "success"])
    connections = _wire_outbox_dispatch(
        monkeypatch,
        row,
        lambda: _ScriptedSMTP(next(outcomes)),
        use_real_sender=True,
        real_sender_kind="confirmation",
    )
    redis = AtomicMailBudgetRedis()
    original_eval = redis.eval
    finish_failures = 2

    async def eval_with_lost_finish_results(
        script: str, numkeys: int, *args: Any
    ) -> list[int]:
        nonlocal finish_failures
        if script == mail_budget._FINISH_SCRIPT and finish_failures:
            finish_failures -= 1
            raise ConnectionError("redis unavailable while recording result")
        return await original_eval(script, numkeys, *args)

    async def get_redis() -> Any:
        return redis

    monkeypatch.setattr(redis, "eval", eval_with_lost_finish_results)
    monkeypatch.setattr(mail_budget, "get_redis", get_redis)
    monkeypatch.setattr(mail_budget, "report_mail_failure", lambda **_kwargs: None)
    original_reserve_mail = mail_budget.reserve_mail
    reclaim_flags: list[bool] = []

    async def record_reserve_mail(
        *, priority: MailPriority, message_id: str
    ) -> MailReservation:
        reclaim_flags.append(current_mail_reserved_retry())
        return await original_reserve_mail(priority=priority, message_id=message_id)

    monkeypatch.setattr(tasks, "reserve_mail", record_reserve_mail)

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]

    assert row.attempts == 1
    assert row.processed_at is None
    assert connections[0].data_calls == 0
    assert reclaim_flags == [True]

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    metrics = await mail_budget.read_mail_budget_metrics()

    assert row.processed_at is not None
    assert len(connections) == 2
    assert [connection.send_message_calls for connection in connections] == [1, 1]
    assert [connection.data_calls for connection in connections] == [0, 1]
    assert reclaim_flags == [True, True]
    assert metrics["admitted"] == 1
    assert metrics["priority:high"] == 1
    assert metrics["sent"] == 1
    assert metrics["failed"] == 0


@pytest.mark.asyncio
async def test_outbox_recupera_reserva_ambigua_antes_de_smtp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    row = _OutboxMailRow()
    outcomes = iter(["success"])
    connections = _wire_outbox_dispatch(
        monkeypatch,
        row,
        lambda: _ScriptedSMTP(next(outcomes)),
        use_real_sender=True,
        real_sender_kind="confirmation",
    )
    redis = AtomicMailBudgetRedis()
    original_eval = redis.eval
    lost_responses = 2

    async def eval_with_lost_reserve_responses(
        script: str, numkeys: int, *args: Any
    ) -> list[int]:
        nonlocal lost_responses
        result = await original_eval(script, numkeys, *args)
        if script == mail_budget._RESERVE_SCRIPT and lost_responses:
            lost_responses -= 1
            raise ConnectionError("redis reply lost after reservation")
        return result

    async def get_redis() -> Any:
        return redis

    monkeypatch.setattr(redis, "eval", eval_with_lost_reserve_responses)
    monkeypatch.setattr(mail_budget, "get_redis", get_redis)
    monkeypatch.setattr(mail_budget, "report_mail_failure", lambda **_kwargs: None)
    original_reserve_mail = mail_budget.reserve_mail
    reclaim_flags: list[bool] = []

    async def record_reserve_mail(
        *, priority: MailPriority, message_id: str
    ) -> MailReservation:
        reclaim_flags.append(current_mail_reserved_retry())
        return await original_reserve_mail(priority=priority, message_id=message_id)

    monkeypatch.setattr(tasks, "reserve_mail", record_reserve_mail)

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]

    assert row.attempts == 0
    assert row.processed_at is None
    assert connections == []
    assert reclaim_flags == [True]
    metrics = await mail_budget.read_mail_budget_metrics()
    assert metrics["admitted"] == 1
    assert metrics["sent"] == 0

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    metrics = await mail_budget.read_mail_budget_metrics()

    assert row.processed_at is not None
    assert len(connections) == 1
    assert connections[0].send_message_calls == 1
    assert connections[0].data_calls == 1
    assert reclaim_flags == [True, True]
    assert metrics["admitted"] == 1
    assert metrics["priority:high"] == 1
    assert metrics["sent"] == 1


@pytest.mark.parametrize(
    "real_sender_kind", ["confirmation", "store_notification", "reminder"]
)
@pytest.mark.asyncio
async def test_fallos_pre_data_respetan_el_maximo_original_del_outbox(
    monkeypatch: pytest.MonkeyPatch,
    real_sender_kind: str,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    row = _OutboxMailRow()
    connections = _wire_outbox_dispatch(
        monkeypatch,
        row,
        lambda: _ScriptedSMTP("connection-before-data"),
        use_real_sender=True,
        real_sender_kind=real_sender_kind,
    )

    for _ in range(WEBHOOK_INBOX_MAX_ATTEMPTS):
        await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    metrics = await mail_budget.read_mail_budget_metrics()

    assert row.attempts == WEBHOOK_INBOX_MAX_ATTEMPTS
    assert row.processed_at is not None
    assert len(connections) == WEBHOOK_INBOX_MAX_ATTEMPTS
    assert all(connection.send_message_calls == 1 for connection in connections)
    assert all(connection.data_calls == 0 for connection in connections)
    assert metrics["admitted"] == 1
    assert (
        metrics[f"priority:{'medium' if real_sender_kind == 'reminder' else 'high'}"]
        == 1
    )
    assert metrics["failed"] == WEBHOOK_INBOX_MAX_ATTEMPTS
    assert metrics["sent"] == 0


@pytest.mark.parametrize(
    "real_sender_kind", ["confirmation", "store_notification", "reminder"]
)
@pytest.mark.parametrize(
    "data_error",
    [
        smtplib.SMTPDataError(451, b"temporary DATA rejection"),
        TimeoutError("connection timed out during DATA"),
        smtplib.SMTPServerDisconnected("connection lost during DATA"),
    ],
    ids=["smtp-4xx-after-data", "timeout-after-data", "disconnect-after-data"],
)
@pytest.mark.asyncio
async def test_fallos_tras_entrar_en_data_quedan_terminales(
    monkeypatch: pytest.MonkeyPatch,
    data_error: Exception,
    real_sender_kind: str,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    row = _OutboxMailRow()
    connections = _wire_outbox_dispatch(
        monkeypatch,
        row,
        lambda: _ScriptedSMTP(data_error),
        use_real_sender=True,
        real_sender_kind=real_sender_kind,
    )
    original_reserve_mail = mail_budget.reserve_mail
    reclaim_flags: list[bool] = []

    async def record_reserve_mail(
        *, priority: MailPriority, message_id: str
    ) -> MailReservation:
        reclaim_flags.append(current_mail_reserved_retry())
        return await original_reserve_mail(priority=priority, message_id=message_id)

    monkeypatch.setattr(tasks, "reserve_mail", record_reserve_mail)

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    assert row.attempts == 1
    assert row.processed_at is not None
    assert reclaim_flags == [True]
    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    metrics = await mail_budget.read_mail_budget_metrics()

    assert len(connections) == 1
    assert connections[0].send_message_calls == 1
    assert connections[0].data_calls == 1
    assert reclaim_flags == [True]
    assert metrics["admitted"] == 1
    assert metrics["failed"] == 1
    assert metrics["sent"] == 0


@pytest.mark.parametrize("direct_sender_kind", ["confirmation", "store_notification"])
@pytest.mark.asyncio
async def test_sender_directo_no_habilita_retry_pre_data(
    monkeypatch: pytest.MonkeyPatch,
    direct_sender_kind: str,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    monkeypatch.setattr(settings, "MAIL_BUDGET_TIMEZONE", "UTC")
    monkeypatch.setattr(settings, "MAIL_BUDGET_RESET_HOUR", 0)
    if direct_sender_kind == "confirmation":
        monkeypatch.setattr(tasks, "_confirmation_subject", lambda _details: "Subject")
        monkeypatch.setattr(tasks, "_confirmation_body", lambda _details: "Body")
    smtp = tasks.SmtpSession()
    connection = _ScriptedSMTP("connection-before-data")
    monkeypatch.setattr(smtp, "_connect", lambda: connection)
    retry_flags: list[bool] = []
    original_reserve_mail = mail_budget.reserve_mail

    async def record_reserve_mail(
        *, priority: MailPriority, message_id: str
    ) -> MailReservation:
        retry_flags.append(current_mail_pre_data_retry())
        return await original_reserve_mail(priority=priority, message_id=message_id)

    monkeypatch.setattr(tasks, "reserve_mail", record_reserve_mail)

    if direct_sender_kind == "confirmation":
        result = await tasks.send_confirmation_email(
            email="client@example.com",
            details={"public_id": "direct-confirmation"},
            smtp=smtp,
        )
    else:
        result = await tasks.send_store_notification_email(
            email="store@example.com",
            title="New appointment",
            body="A client booked a time.",
            smtp=smtp,
        )
    metrics = await mail_budget.read_mail_budget_metrics()

    assert result["status"] == "failed"
    assert retry_flags == [False]
    assert smtp.last_delivery_retryable is False
    assert connection.send_message_calls == 1
    assert connection.data_calls == 0
    assert metrics["admitted"] == 1
    assert metrics["failed"] == 1
    assert metrics["sent"] == 0
