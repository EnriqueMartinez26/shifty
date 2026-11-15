from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import modules.notifications.tasks as notification_tasks


@pytest.mark.asyncio
async def test_confirmation_send_returns_failed_when_smtp_send_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def smtp_failure(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(notification_tasks, "_send_email", smtp_failure)

    result = await notification_tasks.send_confirmation_email(
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
    staff = SimpleNamespace(
        display_name="Pro Demo", id="st-1", public_id="st-1", kind="person"
    )
    client = SimpleNamespace(email="cliente@example.com", phone="+5491100000000")
    store = SimpleNamespace(send_email_reminders=True, slug="demo", name="Demo")
    return (appointment, service, staff, client, store)


class _FakeRepo:
    """Repo en memoria con el reclamo durable (rowcount 1 solo la primera vez)."""

    claims: list[tuple[str, str]] = []
    releases: list[tuple[str, str]] = []
    schedules: list[tuple[str, str, datetime, dict[str, Any]]] = []
    rows: list[tuple[Any, Any, Any, Any, Any]] = []
    limits: list[int | None] = []
    columns: list[str | None] = []
    claim_result = True
    schedule_result = True

    def __init__(self, db: Any) -> None:
        self.db = db

    async def get_upcoming_for_reminders(
        self,
        starts_after: datetime,
        starts_before: datetime,
        *,
        pending_column: str | None = None,
        limit: int | None = None,
    ) -> list[tuple[Any, Any, Any, Any, Any]]:
        self.limits.append(limit)
        self.columns.append(pending_column)
        return list(self.rows)[:limit]

    async def claim_reminder(
        self, appointment_id: str, column: str, sent_at: datetime
    ) -> bool:
        self.claims.append((appointment_id, column))
        return self.claim_result

    async def release_reminder(self, appointment_id: str, column: str) -> None:
        self.releases.append((appointment_id, column))

    async def schedule_reminder(
        self,
        appointment_id: str,
        column: str,
        scheduled_at: datetime,
        payload: dict[str, Any],
    ) -> bool:
        self.schedules.append((appointment_id, column, scheduled_at, payload))
        return self.schedule_result


def _preparar(
    monkeypatch: pytest.MonkeyPatch, rows: list[Any], *, claim_result: bool = True
) -> list[tuple[str, str, datetime, dict[str, Any]]]:
    _FakeRepo.claims = []
    _FakeRepo.releases = []
    _FakeRepo.schedules = []
    _FakeRepo.limits = []
    _FakeRepo.columns = []
    _FakeRepo.rows = rows
    _FakeRepo.claim_result = claim_result
    _FakeRepo.schedule_result = True
    monkeypatch.setattr(
        notification_tasks, "AsyncSessionFactory", lambda: _FakeSessionFactory()
    )
    monkeypatch.setattr(
        "modules.appointments.repository.AppointmentRepository", _FakeRepo
    )
    return _FakeRepo.schedules


@pytest.mark.asyncio
async def test_el_recordatorio_de_24h_guarda_la_marca_y_el_mail_en_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    _preparar(monkeypatch, [_fila(now, 23)])

    result = await notification_tasks.process_due_appointment_reminders(
        now=now, lookahead_hours=48
    )

    assert result["status"] == "processed"
    assert result["published"] == 1
    assert result["skipped"] == 0
    assert _FakeRepo.schedules[0][0:2] == ("appt-2", "reminder_24h_sent_at")
    payload = _FakeRepo.schedules[0][3]
    assert payload["mail"] == "reminder"
    assert payload["args"]["details"]["stage"] == "24h"
    assert payload["args"]["details"]["rebook_url"].endswith(
        "/b/demo?service=svc-1&staff=st-1"
    )
    assert payload["logical_id"] == "reminder:appt-2:24h"
    assert payload["expires_at"] == _FakeRepo.rows[0][0].starts_at.isoformat()


@pytest.mark.asyncio
async def test_reclamo_perdido_no_reenvia(monkeypatch: pytest.MonkeyPatch) -> None:
    # Otro worker gano el UPDATE ... WHERE col IS NULL: este no manda nada.
    now = datetime.now(timezone.utc)
    _preparar(monkeypatch, [_fila(now, 23)])
    _FakeRepo.schedule_result = False

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    assert result["published"] == 0
    assert len(_FakeRepo.schedules) == 1


@pytest.mark.asyncio
async def test_a_hora_y_media_va_solo_el_de_2h(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    schedules = _preparar(monkeypatch, [_fila(now, 1.5)])

    await notification_tasks.process_due_appointment_reminders(now=now)

    assert schedules[0][0:2] == ("appt-2", "reminder_2h_sent_at")
    assert schedules[0][3]["args"]["details"]["stage"] == "2h"


@pytest.mark.asyncio
async def test_tienda_con_recordatorios_apagados_se_saltea(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    fila = _fila(now, 23)
    fila[4].send_email_reminders = False
    schedules = _preparar(monkeypatch, [fila])

    result = await notification_tasks.process_due_appointment_reminders(now=now)

    assert result["skipped"] == 1
    assert schedules == []
    assert _FakeRepo.claims == []


@pytest.mark.asyncio
async def test_falla_al_guardar_mail_no_sella_el_recordatorio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    _preparar(monkeypatch, [_fila(now, 23)])

    async def fail_schedule(*_args: Any, **_kwargs: Any) -> bool:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(_FakeRepo, "schedule_reminder", fail_schedule)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await notification_tasks.process_due_appointment_reminders(now=now)
