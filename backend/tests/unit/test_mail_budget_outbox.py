from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from core.mail_budget import MailReservation, current_mail_context
from modules.payments import jobs
from modules.notifications import tasks
from modules.notifications.reminders import STAGE_24H


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
