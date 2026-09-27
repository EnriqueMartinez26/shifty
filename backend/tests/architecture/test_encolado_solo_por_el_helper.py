"""Ninguna publicacion a Celery fuera de ``core/enqueue.py``.

F1-03 (plan de rendimiento, R8-02/R9-04, 2026-09-24): ``.delay()`` publica
en el broker de forma sincronica. Llamado desde un ``async def`` congela el
event loop mientras el broker no responde (medido: hasta 33 s). El unico
camino es ``core.enqueue.enqueue``, que corre el publish en un hilo con tope
de tiempo y nunca propaga. Este test falla si aparece un ``.delay(``,
``.apply_async(`` o ``.send_task(`` directo en ``modules/`` o ``core/``.

Los ``send_task`` de beat y el propio Celery no pasan por aca: el schedule
es configuracion (``core/celery_app.py``), no una llamada.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
PUBLICACIONES = {"delay", "apply_async", "send_task"}
CARPETAS = ("modules", "core")
PERMITIDOS = {"core/enqueue.py"}


def test_nadie_publica_en_celery_salteando_el_helper() -> None:
    directas: list[str] = []
    for carpeta in CARPETAS:
        for archivo in (BACKEND / carpeta).rglob("*.py"):
            ruta = archivo.relative_to(BACKEND).as_posix()
            if ruta in PERMITIDOS:
                continue
            tree = ast.parse(archivo.read_text(encoding="utf-8"), filename=ruta)
            for nodo in ast.walk(tree):
                if (
                    isinstance(nodo, ast.Call)
                    and isinstance(nodo.func, ast.Attribute)
                    and nodo.func.attr in PUBLICACIONES
                ):
                    directas.append(f"{ruta}:{nodo.lineno} .{nodo.func.attr}(")
    assert directas == [], (
        "publicacion a Celery sin core.enqueue.enqueue (congela el loop si el "
        f"broker no responde): {directas}"
    )
