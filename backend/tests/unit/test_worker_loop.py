"""El runner de tareas usa un loop persistente por proceso.

Con asyncio.run() por tarea, el pool global de conexiones quedaba atado a un
loop cerrado y la segunda tarea del mismo proceso fallaba. El runner debe
reutilizar el mismo loop entre llamadas y sostener consultas consecutivas
sobre un engine compartido.
"""

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from core.worker_loop import run_in_worker_loop


def test_reutiliza_el_mismo_loop_entre_llamadas() -> None:
    async def which_loop() -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    first = run_in_worker_loop(which_loop())
    second = run_in_worker_loop(which_loop())
    assert first is second
    assert not first.is_closed()


def test_consultas_consecutivas_sobre_un_engine_compartido() -> None:
    # Reproduce el patron del worker: engine global con pool, una tarea
    # tras otra en el mismo proceso.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    async def query() -> int:
        async with engine.connect() as conn:
            return int((await conn.execute(text("select 41 + 1"))).scalar_one())

    try:
        assert run_in_worker_loop(query()) == 42
        assert run_in_worker_loop(query()) == 42
        assert run_in_worker_loop(query()) == 42
    finally:
        run_in_worker_loop(engine.dispose())


def test_un_hijo_forkeado_no_hereda_el_loop_del_padre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def which_loop() -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    parent_loop = run_in_worker_loop(which_loop())
    # Simula el fork: mismo modulo, otro PID.
    monkeypatch.setattr(os, "getpid", lambda: -1)
    child_loop = run_in_worker_loop(which_loop())
    assert child_loop is not parent_loop


def test_un_corte_a_mitad_de_tarea_no_deja_la_corrutina_viva_en_el_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F1-24 (plan de rendimiento, R9, 2026-09-24): corrutina zombi.

    ``SoftTimeLimitExceeded`` lo levanta un handler de senal, y un job pasa
    casi todo su tiempo esperando I/O: la excepcion sale del ``select`` del
    loop, no de adentro de la corrutina. ``run_until_complete`` la propaga
    pero deja la Task PENDIENTE en el loop persistente del proceso, y la
    tarea siguiente del mismo hijo la reanudaba: seguia escribiendo con su
    sesion y su advisory lock de sesion tomado, fuera de todo time limit.

    Se simula el corte haciendo que el ``select`` del loop levante (es donde
    cae la senal). La corrutina cortada tiene que terminar cancelada, con
    sus ``finally`` corridos, y la tarea siguiente no puede reanudarla.
    """
    from celery.exceptions import SoftTimeLimitExceeded

    loop = run_in_worker_loop(_loop_actual())
    reanudada: list[str] = []
    limpiada: list[str] = []

    async def job_que_espera_io() -> None:
        try:
            await asyncio.sleep(0.05)
            reanudada.append("siguio despues del corte")
        finally:
            limpiada.append("finally")

    select_original = loop._selector.select  # type: ignore[attr-defined]

    def select_con_senal(timeout: float | None = None) -> object:
        if timeout is None or timeout > 0:
            # Una sola vez: el loop vuelve a su select normal.
            monkeypatch.setattr(loop._selector, "select", select_original)  # type: ignore[attr-defined]
            raise SoftTimeLimitExceeded()
        return select_original(timeout)

    monkeypatch.setattr(loop._selector, "select", select_con_senal)  # type: ignore[attr-defined]

    with pytest.raises(SoftTimeLimitExceeded):
        run_in_worker_loop(job_que_espera_io())

    # La tarea siguiente del mismo proceso, en el mismo loop.
    run_in_worker_loop(asyncio.sleep(0.2))

    assert reanudada == [], "la tarea siguiente reanudo la corrutina cortada"
    assert limpiada == ["finally"], "la corrutina cortada no corrio sus finally"
    assert not [t for t in asyncio.all_tasks(loop) if not t.done()]


async def _loop_actual() -> asyncio.AbstractEventLoop:
    return asyncio.get_running_loop()
