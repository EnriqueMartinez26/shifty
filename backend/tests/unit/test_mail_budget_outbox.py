from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
import smtplib
from types import SimpleNamespace
from typing import Any

import pytest

from core import mail_budget
from core.config import settings
from core.mail_budget import MailReservation, current_mail_context
from modules.payments import jobs
from modules.payments.model import WEBHOOK_INBOX_MAX_ATTEMPTS
from modules.notifications import tasks
from modules.notifications.reminders import STAGE_24H


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
) -> list[_ScriptedSMTP]:
    connections: list[_ScriptedSMTP] = []

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

    monkeypatch.setattr(jobs, "_claim_next_email", claim)
    monkeypatch.setattr(jobs, "_apply_tenant_context", apply_context)
    monkeypatch.setattr(jobs, "smtp_session", smtp_session)
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
    ("mail_kind", "expected_priority"), [("rebook", "low"), ("confirmation", "high")]
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

    async def send(**_kwargs: Any) -> dict[str, str]:
        contexts.append(current_mail_context())
        return {"status": "sent"}

    monkeypatch.setattr(jobs, "_sender", lambda _kind: send)

    assert await jobs._send_one_pending_email(fila, object()) is None  # type: ignore[arg-type]
    assert contexts == [(expected_priority, "outbox:123")]
    assert current_mail_context() is None


@pytest.mark.parametrize("decision", ["deferred", "unavailable"])
@pytest.mark.asyncio
async def test_recordatorio_preserva_reclamo_sin_reportar_fallo_smtp_por_budget(
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
) -> None:
    appointment = SimpleNamespace(
        id="appointment-1", public_id="public-1", client_email="client@example.com"
    )
    row = (appointment, object(), object(), object(), object())
    claimed: list[tuple[str, str, datetime]] = []
    released: list[tuple[str, str]] = []
    reports: list[dict[str, str]] = []

    class ReminderRepository:
        async def claim_reminder(
            self, appointment_id: str, column: str, now: datetime
        ) -> bool:
            claimed.append((appointment_id, column, now))
            return True

        async def release_reminder(self, appointment_id: str, column: str) -> None:
            released.append((appointment_id, column))

    async def reserve(**kwargs: Any) -> MailReservation:
        assert kwargs == {
            "priority": "medium",
            "message_id": "reminder:public-1:24h",
        }
        return MailReservation(
            decision=decision,  # type: ignore[arg-type]
            window_id="test-window",
            message_key="message",
            attempt_token="attempt",
            priority="medium",
        )

    monkeypatch.setattr(
        tasks, "build_client_details", lambda *_args: {"public_id": "public-1"}
    )
    monkeypatch.setattr(tasks, "_reminder_subject", lambda _details: "Reminder")
    monkeypatch.setattr(tasks, "_reminder_body", lambda _details: "Body")
    monkeypatch.setattr(tasks, "reserve_mail", reserve)
    monkeypatch.setattr(
        tasks, "report_mail_failure", lambda **kwargs: reports.append(kwargs)
    )
    smtp = tasks.SmtpSession()
    monkeypatch.setattr(
        smtp,
        "_send_sync",
        lambda _message: (_ for _ in ()).throw(AssertionError("SMTP must not run")),
    )

    result = await tasks._dispatch_reminder(
        ReminderRepository(),
        row,
        STAGE_24H,
        datetime.now(timezone.utc),
        smtp,
    )

    assert result is False
    assert len(claimed) == 1
    assert released == [("appointment-1", STAGE_24H.column)]
    assert reports == []


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


@pytest.mark.parametrize("first_outcome", ["connection-before-data", "4xx-before-data"])
@pytest.mark.asyncio
async def test_outbox_reintenta_fallo_pre_data_con_mismo_id_y_un_solo_cupo(
    monkeypatch: pytest.MonkeyPatch,
    first_outcome: str,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    row = _OutboxMailRow()
    outcomes = iter([first_outcome, "success"])
    connections = _wire_outbox_dispatch(
        monkeypatch, row, lambda: _ScriptedSMTP(next(outcomes))
    )

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
    assert metrics["priority:high"] == 1
    assert metrics["failed"] == 1
    assert metrics["sent"] == 1


@pytest.mark.asyncio
async def test_fallos_pre_data_respetan_el_maximo_original_del_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    row = _OutboxMailRow()
    connections = _wire_outbox_dispatch(
        monkeypatch, row, lambda: _ScriptedSMTP("connection-before-data")
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
    assert metrics["priority:high"] == 1
    assert metrics["failed"] == WEBHOOK_INBOX_MAX_ATTEMPTS
    assert metrics["sent"] == 0


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
) -> None:
    monkeypatch.setattr(settings, "MAIL_DAILY_BUDGET", 5)
    row = _OutboxMailRow()
    connections = _wire_outbox_dispatch(
        monkeypatch, row, lambda: _ScriptedSMTP(data_error)
    )

    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    assert row.attempts == 1
    assert row.processed_at is not None
    await jobs._dispatch_pending_emails(object())  # type: ignore[arg-type]
    metrics = await mail_budget.read_mail_budget_metrics()

    assert len(connections) == 1
    assert connections[0].send_message_calls == 1
    assert connections[0].data_calls == 1
    assert metrics["admitted"] == 1
    assert metrics["failed"] == 1
    assert metrics["sent"] == 0
