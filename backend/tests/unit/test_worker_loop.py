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
