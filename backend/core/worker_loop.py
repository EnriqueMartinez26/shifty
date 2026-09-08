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
"""

import asyncio
import os
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

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
    return loop.run_until_complete(coro)
