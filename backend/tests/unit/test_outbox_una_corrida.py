"""El tick del outbox corre una sola vez a la vez (plan de rendimiento F0-17).

Con el beat cada 20 s y un lote que puede tardar hasta su presupuesto de 45 s,
dos hijos del worker podian procesar lotes del outbox al mismo tiempo. El
`FOR UPDATE SKIP LOCKED` evita que tomen la MISMA fila, pero no que dos lotes
despachen en paralelo y compitan por el SMTP y el pool. El tick toma el
advisory lock de sesion de los jobs (`_exclusive_job`), como la conciliacion
y el inbox; `process_outbox_batch` sigue sin lock (el panel y las pruebas de
concurrencia lo llaman directo) y conserva su SKIP LOCKED.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from modules.payments import jobs, tasks


def _lock_falso(tomado: bool, pedidos: list[str]) -> Any:
    @asynccontextmanager
    async def _exclusive_job(_db: object, nombre: str) -> AsyncIterator[bool]:
        pedidos.append(nombre)
        yield tomado

    return _exclusive_job


@pytest.mark.asyncio
async def test_el_tick_procesa_el_lote_con_el_lock_tomado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pedidos: list[str] = []
    lotes: list[int] = []

    async def lote(_db: object, *, limit: int) -> dict[str, int]:
        lotes.append(limit)
        return {"processed": 3, "failed": 0, "inspected": 3}

    monkeypatch.setattr(jobs, "_exclusive_job", _lock_falso(True, pedidos))
    monkeypatch.setattr(jobs, "process_outbox_batch", lote)

    resultado = await jobs.process_outbox_tick(object(), limit=25)  # type: ignore[arg-type]

    assert pedidos == [jobs.OUTBOX_JOB_LOCK]
    assert lotes == [25]
    assert resultado == {"processed": 3, "failed": 0, "inspected": 3}


@pytest.mark.asyncio
async def test_con_otra_corrida_adentro_el_tick_no_hace_nada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pedidos: list[str] = []

    async def lote(_db: object, *, limit: int) -> dict[str, int]:
        raise AssertionError("proceso un lote sin el lock")

    monkeypatch.setattr(jobs, "_exclusive_job", _lock_falso(False, pedidos))
    monkeypatch.setattr(jobs, "process_outbox_batch", lote)

    resultado = await jobs.process_outbox_tick(object(), limit=25)  # type: ignore[arg-type]

    assert pedidos == [jobs.OUTBOX_JOB_LOCK]
    assert resultado == {"processed": 0, "failed": 0, "inspected": 0}


def test_el_lock_del_outbox_es_propio() -> None:
    otros = {jobs.EXPIRE_JOB_LOCK, jobs.INBOX_JOB_LOCK, jobs.RECONCILE_JOB_LOCK}
    assert jobs.OUTBOX_JOB_LOCK not in otros


def test_la_tarea_del_beat_pasa_por_el_tick() -> None:
    """La tarea de Celery llama al tick (con lock), no al lote suelto."""
    assert vars(tasks)["process_outbox_tick"] is jobs.process_outbox_tick
    assert not hasattr(tasks, "process_outbox_batch"), (
        "la tarea importa el lote sin lock: el beat podria saltearse el lock"
    )
