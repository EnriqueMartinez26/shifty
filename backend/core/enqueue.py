"""Unico camino para publicar una tarea de Celery desde codigo async.

F1-03 (plan de rendimiento, R8-02/R9-04, 2026-09-24): ``task.delay()`` es
SINCRONICO: abre la conexion con el broker y publica en el hilo que lo llama.
Desde un ``async def`` eso es el event loop entero: con RabbitMQ inalcanzable
cada publish tardaba ~16 s (hasta 33 s) y la API no atendia a nadie mas.

``enqueue`` publica en un hilo (``asyncio.to_thread``) y deja de esperar a los
``timeout`` segundos (``asyncio.wait_for``). Nunca propaga: un fallo de
encolado es un fallo de envio, se registra y el llamador decide con el
``bool``. El hilo cortado por el tope puede terminar de publicar despues; el
llamador lo trata como no encolado (para un OTP, el cliente vuelve a pedir el
codigo, que es lo que ya pasaba con un envio fallido).

El log lleva solo el nombre de la tarea y el tipo de error: los argumentos
traen emails y codigos, y el texto de un error de conexion repite la URL del
broker con su clave. ``tests/architecture/test_encolado_solo_por_el_helper.py``
impide publicar salteando esta funcion.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Mapping
from typing import Any

import structlog

logger = structlog.get_logger()

ENQUEUE_TIMEOUT_SECONDS = 2.0


def _task_name(task: Any) -> str:
    name = getattr(task, "name", None)
    return name if isinstance(name, str) else type(task).__name__


async def enqueue(
    task: Any,
    *args: Any,
    timeout: float = ENQUEUE_TIMEOUT_SECONDS,
    options: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> bool:
    """Publica ``task`` con ``args``/``kwargs``; True si el broker lo acepto.

    ``options`` son las opciones de ``apply_async`` (``countdown``, ``queue``);
    sin ellas se usa ``delay``. ``timeout`` es de este helper, no de la tarea.
    """
    if options:
        publish = functools.partial(
            task.apply_async, args=args, kwargs=kwargs, **options
        )
    else:
        publish = functools.partial(task.delay, *args, **kwargs)
    try:
        await asyncio.wait_for(asyncio.to_thread(publish), timeout)
    except Exception as exc:
        logger.warning(
            "enqueue_failed",
            task=_task_name(task),
            error_type=type(exc).__name__,
        )
        return False
    return True


__all__ = ["ENQUEUE_TIMEOUT_SECONDS", "enqueue"]
