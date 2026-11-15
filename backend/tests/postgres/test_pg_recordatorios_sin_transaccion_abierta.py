"""El scheduler solo persiste recordatorios; el SMTP corre en otro worker."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import modules.notifications.tasks as tasks
from modules.appointments.repository import AppointmentRepository
from tests.postgres.test_pg_recordatorios_skip_locked import (
    _scheduled_reminders,
    _turnos_de_manana,
)

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_scheduler_persiste_sin_smtp_ni_transaccion_abierta(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turnos, primero = await _turnos_de_manana(client, app_sessions)
    monkeypatch.setattr(tasks, "AsyncSessionFactory", app_sessions)

    async def smtp_unexpected(**_kwargs: object) -> None:
        raise AssertionError("el scheduler no debe entregar correo")

    monkeypatch.setattr(tasks, "notify_client_reminder", smtp_unexpected)
    estados_de_transaccion: list[bool] = []
    schedule_reminder = AppointmentRepository.schedule_reminder

    async def schedule_and_check(
        repo: AppointmentRepository,
        *args: object,
        **kwargs: object,
    ) -> bool:
        scheduled = await schedule_reminder(repo, *args, **kwargs)  # type: ignore[arg-type]
        estados_de_transaccion.append(repo.db.in_transaction())
        return scheduled

    monkeypatch.setattr(AppointmentRepository, "schedule_reminder", schedule_and_check)
    resultado = await tasks.process_due_appointment_reminders(
        now=primero.replace(hour=6)
    )

    assert resultado["published"] == len(turnos)
    assert estados_de_transaccion == [False] * len(turnos)
    assert len(await _scheduled_reminders(app_sessions)) == len(turnos)
