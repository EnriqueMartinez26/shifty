"""Pipeline de ``redis.asyncio`` para los dobles de Redis de los tests.

F3-09 (plan de rendimiento, R1-08, 2026-09-24): el cache de disponibilidad
manda sus GETEX e INCR+EXPIRE en un pipeline (una ida y vuelta). Como en
redis-py, cada comando se ENCOLA (devuelve el pipeline, no se espera) y todo
corre recien en ``execute``: un doble que falla en un comando falla en el
``execute``, igual que un Redis caido. Los comandos se resuelven contra el
doble en el momento de encolar, asi que un ``monkeypatch`` sobre la instancia
(p. ej. el espia de ``incr`` de la caracterizacion del alta) se sigue viendo.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class PipelineDouble:
    def __init__(self, owner: Any) -> None:
        self._owner = owner
        self._ops: list[
            tuple[Callable[..., Awaitable[Any]], tuple[Any, ...], dict[str, Any]]
        ] = []

    def __getattr__(self, name: str) -> Callable[..., PipelineDouble]:
        metodo = getattr(self._owner, name)

        def encolar(*args: Any, **kwargs: Any) -> PipelineDouble:
            self._ops.append((metodo, args, kwargs))
            return self

        return encolar

    async def execute(self, raise_on_error: bool = True) -> list[Any]:
        ops, self._ops = self._ops, []
        return [await metodo(*args, **kwargs) for metodo, args, kwargs in ops]

    async def __aenter__(self) -> PipelineDouble:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._ops = []
