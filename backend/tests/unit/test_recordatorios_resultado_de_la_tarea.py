"""AUD2-B4-10 (2026-09-20): la tarea de Celery no puede tirar la senal del lote.

Sintoma: S-06 agrego ``unexamined`` (filas del lote sin revisar) y
``batch_full`` (el lote vino lleno, puede haber mas afuera del tope) para que
se sepa cuando una corrida quedo corta. El wrapper de Celery los descartaba:
el resultado de la tarea -lo que se ve en el backend de resultados y en
cualquier monitor- traia solo ``published`` y ``skipped``. Con AUD2-B4-04
encima, la unica evidencia de que se estaban perdiendo recordatorios de 24 h
era una linea de ``info`` entre todas las demas.

Los tests llaman a la tarea de forma sincronica a proposito: ``run_in_worker
_loop`` se niega a anidarse en un loop activo, asi que este es el unico modo
de ejercitar el wrapper de verdad y no una copia.
"""

from __future__ import annotations

from typing import Any

import pytest
from structlog.testing import capture_logs

import modules.notifications.tasks as tasks


def _corrida(**totales: Any) -> Any:
    base = {
        "status": "processed",
        "published": 0,
        "skipped": 0,
        "unexamined": 0,
        "batch_full": False,
        "window_start": "2026-09-20T00:00:00+00:00",
        "window_end": "2026-09-22T00:00:00+00:00",
    }
    base.update(totales)

    async def fake(**_kwargs: Any) -> dict[str, Any]:
        return base

    return fake


def test_la_tarea_devuelve_las_cuatro_metricas_y_avisa_del_lote_corto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tasks,
        "process_due_appointment_reminders",
        _corrida(published=2, skipped=1, unexamined=7, batch_full=True),
    )

    with capture_logs() as eventos:
        resultado = tasks.process_appointment_reminders()

    assert resultado == {
        "published": 2,
        "skipped": 1,
        "unexamined": 7,
        "batch_full": True,
    }
    aviso = next(e for e in eventos if e["event"] == "reminders_batch_incompleto")
    # Con contexto: sin el tope y el presupuesto, el numero no dice que hacer.
    assert aviso["batch_limit"] == tasks.REMINDER_BATCH_LIMIT
    assert aviso["time_budget_seconds"] == tasks.REMINDER_TIME_BUDGET_SECONDS
    assert aviso["unexamined"] == 7
    assert aviso["batch_full"] is True


def test_una_corrida_completa_no_avisa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tasks, "process_due_appointment_reminders", _corrida(published=3)
    )

    with capture_logs() as eventos:
        resultado = tasks.process_appointment_reminders()

    assert resultado["batch_full"] is False
    assert resultado["unexamined"] == 0
    assert [e for e in eventos if e["event"] == "reminders_batch_incompleto"] == []
