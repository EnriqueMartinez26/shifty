"""Una funcion ``enqueue_*`` tiene que encolar de verdad.

B4-04 (2026-09-18): los helpers ``enqueue_*_email`` de
``modules/notifications/tasks.py`` no encolaban nada: mandaban SMTP
sincronico en el camino del llamador (el 201 de la reserva publica esperaba
al SMTP; el lote del outbox tambien). El nombre escondia el costo. Se
renombraron a ``send_*_email``. Este test falla si vuelve a aparecer en el
backend una funcion ``enqueue_*`` que no despache a una cola (Celery
``.delay``/``.apply_async``/``send_task`` o el outbox ``.publish``).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[2]
DESPACHOS = {"delay", "apply_async", "send_task", "publish"}
EXCLUIDOS = {".venv", "tests", "__pycache__", "alembic"}


def _archivos() -> list[Path]:
    return [
        p
        for p in BACKEND.rglob("*.py")
        if not EXCLUIDOS.intersection(p.relative_to(BACKEND).parts)
    ]


# F1-03 (2026-09-24): el helper unico de encolado (``core.enqueue.enqueue``)
# publica con ``.delay``/``.apply_async`` en un hilo con tope de tiempo; llamarlo
# es encolar de verdad.
HELPER_DE_ENCOLADO = "enqueue"


def _despacha_a_una_cola(funcion: ast.AST) -> bool:
    for nodo in ast.walk(funcion):
        if not isinstance(nodo, ast.Call):
            continue
        if isinstance(nodo.func, ast.Attribute) and nodo.func.attr in DESPACHOS:
            return True
        if isinstance(nodo.func, ast.Name) and nodo.func.id == HELPER_DE_ENCOLADO:
            return True
    return False


def test_ninguna_funcion_enqueue_manda_en_linea() -> None:
    impostoras: list[str] = []
    for archivo in _archivos():
        tree = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
        for nodo in ast.walk(tree):
            if (
                isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef))
                and nodo.name.startswith("enqueue_")
                and not _despacha_a_una_cola(nodo)
            ):
                ruta = archivo.relative_to(BACKEND).as_posix()
                impostoras.append(f"{ruta}:{nodo.lineno} {nodo.name}")
    assert impostoras == [], (
        "funciones enqueue_* que no encolan (se llaman send_* si mandan en "
        f"linea): {impostoras}"
    )


class _Cola:
    def __init__(self) -> None:
        self.encolados: list[tuple[Any, ...]] = []

    def delay(self, *args: Any) -> None:
        self.encolados.append(args)


@pytest.mark.asyncio
async def test_los_mails_de_la_reserva_publica_se_encolan_con_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F2-01 (2026-09-24): ``enqueue_registration_email`` y
    ``enqueue_confirmation_email`` publican ``send_booking_email`` con el tipo
    de mail, la tienda y el turno. Ni email ni nombre en el broker (PV-19): el
    worker relee el turno."""
    import modules.notifications.tasks as tasks

    cola = _Cola()
    monkeypatch.setattr(tasks, "send_booking_email", cola)

    assert await tasks.enqueue_registration_email(
        store_id="tienda-1", appointment_id="turno-1"
    )
    assert await tasks.enqueue_confirmation_email(
        store_id="tienda-1", appointment_id="turno-2"
    )

    assert cola.encolados == [
        ("registration", "tienda-1", "turno-1"),
        ("confirmation", "tienda-1", "turno-2"),
    ]
