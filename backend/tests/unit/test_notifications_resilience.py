from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import modules.notifications.tasks as notification_tasks


@pytest.mark.asyncio
async def test_confirmation_enqueue_returns_failed_when_smtp_send_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def smtp_failure(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(notification_tasks, "_send_email", smtp_failure)

    result = await notification_tasks.enqueue_confirmation_email(
        email="cliente@example.com",
        details={"public_id": "appt-1", "service": "Consulta", "staff": "Pro Demo"},
    )

    assert result == {"status": "failed", "reason": "RuntimeError"}


class _FakeSessionFactory:
    async def __aenter__(self) -> SimpleNamespace:
        # El task fija el contexto RLS (set_tenant_context + _apply_tenant_context),
        # que consulta el dialecto de la conexion. Se expone una connection()
        # fake que reporta sqlite para que _apply_tenant_context haga no-op.
        async def _connection() -> SimpleNamespace:
            return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        return SimpleNamespace(connection=_connection)

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


def _fila(now: datetime, horas_hasta: float) -> tuple[Any, Any, Any, Any, Any]:
    appointment = SimpleNamespace(
        id="appt-2",
        public_id="appt-2",
        starts_at=now + timedelta(hours=horas_hasta),
        created_at=now - timedelta(days=3),
        reminder_24h_sent_at=None,
        reminder_2h_sent_at=None,
        client_name="Cliente",
    )
    service = SimpleNamespace(name="Consulta", public_id="svc-1")
    staff = SimpleNamespace(display_name="Pro Demo", id="st-1", kind="person")
    client = SimpleNamespace(email="cliente@example.com", phone="+5491100000000")
    store = SimpleNamespace(send_email_reminders=True, slug="demo", name="Demo")
    return (appointment, service, staff, client, store)


class _FakeRepo:
    """Repo en memoria con el reclamo durable (rowcount 1 solo la primera vez)."""

    claims: list[tuple[str, str]] = []
    releases: list[tuple[str, str]] = []
    rows: list[tuple[Any, Any, Any, Any, Any]] = []
    claim_result = True

    def __init__(self, db: Any) -> None:
        self.db = db

    async def get_upcoming_for_reminders(
        self, starts_after: datetime, starts_before: datetime
    ) -> list[tuple[Any, Any, Any, Any, Any]]:
        return list(self.rows)

    async def claim_reminder(
        self, appointment_id: str, column: str, sent_at: datetime
    ) -> bool:
        self.claims.append((appointment_id, column))
        return self.claim_result

    async def release_reminder(self, appointment_id: str, column: str) -> None:
        self.releases.append((appointment_id, column))


def _preparar(
    monkeypatch: pytest.MonkeyPatch, rows: list[Any], *, claim_result: bool = True
) -> list[dict[str, Any]]:
    enviados: list[dict[str, Any]] = []

    async def fake_notify_client_reminder(
        *, phone: str | None, email: str | None, details: dict[str, Any]
    ) -> dict[str, str]:
        enviados.append(details)
        return {"status": "sent", "channel": "email", "to": email or ""}

    _FakeRepo.claims = []
    _FakeRepo.releases = []
    _FakeRepo.rows = rows
    _FakeRepo.claim_result = claim_result
    monkeypatch.setattr(
        notification_tasks, "AsyncSessionFactory", lambda: _FakeSessionFactory()
    )
    monkeypatch.setattr(
        notification_tasks, "notify_client_reminder", fake_notify_client_reminder
    )
    monkeypatch.setattr(
        "modules.appointments.repository.AppointmentRepository", _FakeRepo
    )
    return enviados


@pytest.mark.asyncio
async def test_el_recordatorio_de_24h_reclama_la_marca_y_envia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    enviados = _preparar(monkeypatch, [_fila(now, 23)])

    result = await notification_tasks.process_due_appointment_reminders(
        now=now, lookahead_hours=48
    )

    assert result["status"] == "processed"
    assert result["published"] == 1
    assert result["skipped"] == 0
    assert _FakeRepo.claims == [("appt-2", "reminder_24h_sent_at")]
    assert enviados[0]["stage"] == "24h"
    assert enviados[0]["rebook_url"].endswith("/b/demo?service=svc-1&staff=st-1")


@pytest.mark.asyncio
async def test_reclamo_perdido_no_reenvia(monkeypatch: pytest.MonkeyPatch) -> None:
    # Otro worker gano el UPDATE ... WHERE col IS NULL: este no manda nada.
    now = datetime.now(timezone.utc)
    enviados = _preparar(monkeypatch, [_fila(now, 23)], claim_result=False)

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    assert result["published"] == 0
    assert enviados == []


@pytest.mark.asyncio
async def test_a_hora_y_media_va_solo_el_de_2h(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    enviados = _preparar(monkeypatch, [_fila(now, 1.5)])

    await notification_tasks.process_due_appointment_reminders(now=now)

    assert _FakeRepo.claims == [("appt-2", "reminder_2h_sent_at")]
    assert enviados[0]["stage"] == "2h"


@pytest.mark.asyncio
async def test_tienda_con_recordatorios_apagados_se_saltea(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    fila = _fila(now, 23)
    fila[4].send_email_reminders = False
    enviados = _preparar(monkeypatch, [fila])

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    assert result["skipped"] == 1
    assert enviados == []
    assert _FakeRepo.claims == []


@pytest.mark.asyncio
async def test_envio_fallido_libera_la_marca(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    _preparar(monkeypatch, [_fila(now, 23)])

    async def explota(**kwargs: Any) -> dict[str, str]:
        raise RuntimeError("SMTP send failed")

    monkeypatch.setattr(notification_tasks, "notify_client_reminder", explota)

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    assert result["published"] == 0
    assert _FakeRepo.releases == [("appt-2", "reminder_24h_sent_at")]
