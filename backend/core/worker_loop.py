"""Un event loop persistente por proceso para las tareas de Celery.

Cada tarea hacia ``asyncio.run(_run())``: un loop nuevo por llamada, cerrado
al terminar. Pero el ``engine`` de SQLAlchemy es global y su pool guarda
conexiones asyncpg atadas al loop que las creo. La siguiente tarea en el
mismo proceso hijo recibia una conexion de un loop ya cerrado y moria con
"attached to a different loop" / "Event loop is closed" (visto en vivo:
expire_unpaid_appointments fallaba en cada corrida que no fuera la primera
de su proceso).

Celery prefork ejecuta UNA tarea por vez en cada hijo, asi que un loop por
proceso mantiene pool y loop alineados y ademas reutiliza conexiones. Se
indexa por PID: un hijo forkeado no hereda el loop del padre.

F1-24 (plan de rendimiento, R9, 2026-09-24): un loop que sobrevive a la tarea
tambien sobrevive a lo que la tarea deja pendiente. ``SoftTimeLimitExceeded``
lo levanta un handler de senal y, como un job pasa casi todo su tiempo
esperando I/O, casi siempre sale del ``select`` del loop y no de adentro de
la corrutina: ``run_until_complete`` propagaba la excepcion y dejaba la Task
viva. La tarea siguiente del mismo hijo la reanudaba, con su sesion y su
advisory lock de sesion tomados y fuera de todo time limit. Ante cualquier
``BaseException`` se cancelan las tareas pendientes del loop y se drena
(con tope) para que corran sus ``finally``: sueltan el lock y la conexion.
"""

import asyncio
import logging
import os
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

# Tope del drenaje tras un corte. Tiene que entrar holgado entre el soft y el
# hard time limit de Celery: alcanza para soltar un advisory lock y devolver
# una conexion, no para terminar el trabajo cortado.
DRAIN_TIMEOUT_SECONDS = 5.0

_loop: asyncio.AbstractEventLoop | None = None
_loop_pid: int | None = None


def _process_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_pid
    pid = os.getpid()
    if _loop is None or _loop_pid != pid or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        _loop_pid = pid
        asyncio.set_event_loop(_loop)
    return _loop


def run_in_worker_loop(coro: Coroutine[Any, Any, T]) -> T:
    """Ejecuta la corrutina en el loop del proceso (reemplazo de asyncio.run)."""
    loop = _process_loop()
    if loop.is_running():
        # Dentro de un loop activo (tests async) no se puede anidar: que el
        # llamador use ``await`` directamente.
        raise RuntimeError("run_in_worker_loop no puede anidarse en un loop activo")
    task = loop.create_task(coro)
    try:
        return loop.run_until_complete(task)
    except BaseException:
        _cancel_and_drain(loop)
        raise


def _cancel_and_drain(loop: asyncio.AbstractEventLoop) -> None:
    """Cancela lo que quedo pendiente en el loop y le da tiempo a limpiar.

    Nunca levanta: la excepcion que importa es la del corte, que el llamador
    ya esta propagando. Si el drenaje no termina en el tope, las tareas quedan
    canceladas igual y no se reanudan como si nada en la tarea siguiente.
    """
    pendientes = [t for t in asyncio.all_tasks(loop) if not t.done()]
    if not pendientes:
        return
    for pendiente in pendientes:
        pendiente.cancel()
    try:
        loop.run_until_complete(asyncio.wait(pendientes, timeout=DRAIN_TIMEOUT_SECONDS))
    except BaseException:
        logger.warning("worker_loop_drain_interrupted", exc_info=True)
