"""S-06 (2026-09-18): el lote de recordatorios toma sus filas con SKIP LOCKED.

Sintoma (revision de B4-02): ``get_upcoming_for_reminders`` seleccionaba el
lote sin ``FOR UPDATE SKIP LOCKED`` (regla 8), asi que dos corridas solapadas
del beat recorrian las mismas filas; la unica exclusion era el reclamo
``UPDATE ... WHERE col IS NULL``. Ademas el resultado informaba ``deferred``
contando solo las filas TRAIDAS que el presupuesto no alcanzo a revisar: con
mas turnos vencidos que el tope, lo que quedaba afuera del lote no aparecia y
el numero subestimaba lo pendiente.

Decision sobre ``deferred``: saber cuanto quedo sin procesar de verdad exige
otra consulta (las filas mas alla del tope y las que otro worker tiene
bloqueadas no se ven). Se renombra a lo que el numero SI es:
``unexamined`` (filas del lote que el presupuesto no alcanzo a revisar) y se
suma ``batch_full`` (el lote vino lleno: puede haber mas afuera del tope).

SQLite ignora ``FOR UPDATE``: aca se verifica la sentencia; la concurrencia
real vive en ``tests/postgres/test_pg_recordatorios_skip_locked.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as notification_tasks
from modules.appointments.model import Appointment
from modules.appointments.repository import AppointmentRepository
from tests.integration.test_recordatorios_lote_y_presupuesto import (
    _filas_vencidas,
    _RelojFalso,
)
from tests.unit.test_notifications_resilience import _FakeRepo, _preparar

# El constructor del dialecto no tiene tipos; solo se usa para compilar el SQL.
_DIALECTO_PG: Any = postgresql.dialect


def _espiar_sentencias(
    monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> list[Any]:
    ejecutadas: list[Any] = []
    ejecutar = session.execute

    async def execute_espia(statement: Any, *args: Any, **kwargs: Any) -> Any:
        ejecutadas.append(statement)
        return await ejecutar(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", execute_espia)
    return ejecutadas


@pytest.mark.asyncio
async def test_el_lote_de_recordatorios_bloquea_solo_turnos_con_skip_locked(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ejecutadas = _espiar_sentencias(monkeypatch, test_session)
    now = datetime.now(timezone.utc)

    await AppointmentRepository(test_session).get_upcoming_for_reminders(
        now, now + timedelta(hours=48), limit=10
    )

    lotes = [
        s
        for s in ejecutadas
        if isinstance(s, Select)
        and s.column_descriptions
        and s.column_descriptions[0].get("entity") is Appointment
    ]
    assert len(lotes) == 1
    for_update = lotes[0]._for_update_arg
    assert for_update is not None and for_update.skip_locked, (
        "el lote de recordatorios se selecciona sin FOR UPDATE SKIP LOCKED: "
        "dos corridas solapadas recorren las mismas filas (regla 8)"
    )
    sql = str(lotes[0].compile(dialect=_DIALECTO_PG()))
    # El JOIN trae servicio, profesional, cliente y tienda: se bloquea SOLO la
    # fila del turno. Bloquear la tienda haria que un lock sobre ella saltee
    # todos sus turnos.
    assert "FOR UPDATE OF appointments SKIP LOCKED" in sql, sql
    assert "ORDER BY appointments.starts_at" in sql
    assert "LIMIT" in sql


@pytest.mark.asyncio
async def test_el_resultado_informa_filas_sin_revisar_y_lote_lleno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    _preparar(monkeypatch, _filas_vencidas(now, 5))
    reloj = _RelojFalso()
    monkeypatch.setattr(
        notification_tasks, "time", SimpleNamespace(monotonic=reloj.monotonic)
    )

    async def envio_lento(
        *,
        phone: str | None,
        email: str | None,
        details: dict[str, Any],
        smtp: Any = None,
    ) -> dict[str, str]:
        reloj.ahora += notification_tasks.REMINDER_TIME_BUDGET_SECONDS * 0.6
        return {"status": "sent", "channel": "email", "to": email or ""}

    monkeypatch.setattr(notification_tasks, "notify_client_reminder", envio_lento)

    # Hay 5 vencidos y el tope es 4: el lote vino lleno y, de los 4 traidos,
    # el presupuesto alcanzo para 2. El quinto nunca se vio: no se cuenta como
    # "sin revisar", lo avisa batch_full.
    result = await notification_tasks.process_due_appointment_reminders(
        now=now, limit=4
    )
    assert result["published"] == 2
    assert result["unexamined"] == 2
    assert result["batch_full"] is True
    assert "deferred" not in result
    # Una consulta por etapa desde AUD2-B4-04, cada una con el mismo tope.
    assert _FakeRepo.limits == [4, 4]

    # Sin presion de tiempo y con lugar de sobra: nada sin revisar ni lote lleno.
    _preparar(monkeypatch, _filas_vencidas(now, 3))
    monkeypatch.setattr(
        notification_tasks, "time", SimpleNamespace(monotonic=lambda: 0.0)
    )
    result = await notification_tasks.process_due_appointment_reminders(now=now)
    assert result["published"] == 3
    assert result["unexamined"] == 0
    assert result["batch_full"] is False
