"""Ningun ``except Exception`` de un job se traga el soft time limit de Celery.

Revision independiente de perf/f2b (2026-09-24): ``SoftTimeLimitExceeded`` es
una ``Exception``. Los lotes envuelven cada item en ``except Exception`` para
que un fallo no se lleve al resto, asi que el corte de Celery se contaba como
fallo del item (el inbox hasta le gastaba un ``attempts``, regla 7) y el lote
SEGUIA hasta el hard limit, que mata el proceso sin ``finally``. El circuit
breaker, igual: lo contaba como falla de Mercado Pago.

Regla: en ``modules/*/jobs.py``, ``modules/*/tasks.py`` y
``core/circuit_breaker.py``, todo ``try`` con un handler de ``Exception`` (o
``BaseException``, o ``except:``) tiene ANTES un
``except SoftTimeLimitExceeded`` que termina en ``raise``, salvo que el propio
handler termine en ``raise`` (re-levanta la misma excepcion).
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
AMPLIOS = {"Exception", "BaseException"}
# Transitorio: perf/f2a reescribe los envios de este archivo; las guardas se
# ponen sobre su version al integrar y esta excepcion se borra en ese commit.
PENDIENTES_DEL_MERGE = {"modules/notifications/tasks.py"}
GUARDA = "SoftTimeLimitExceeded"


def _archivos() -> list[Path]:
    modulos = BACKEND / "modules"
    return sorted(
        [*modulos.glob("*/jobs.py"), *modulos.glob("*/tasks.py")]
        + [BACKEND / "core" / "circuit_breaker.py"]
    )


def _nombres(tipo: ast.expr | None) -> set[str]:
    if tipo is None:
        return {"BaseException"}
    if isinstance(tipo, ast.Tuple):
        return set().union(*(_nombres(e) for e in tipo.elts))
    if isinstance(tipo, ast.Name):
        return {tipo.id}
    if isinstance(tipo, ast.Attribute):
        return {tipo.attr}
    return set()


def _termina_en_raise(handler: ast.ExceptHandler) -> bool:
    ultimo = handler.body[-1]
    return isinstance(ultimo, ast.Raise) and ultimo.exc is None


def _violaciones(fuente: str, ruta: str) -> list[str]:
    malas: list[str] = []
    for nodo in ast.walk(ast.parse(fuente, filename=ruta)):
        if not isinstance(nodo, ast.Try):
            continue
        guardado = False
        for handler in nodo.handlers:
            nombres = _nombres(handler.type)
            if GUARDA in nombres and _termina_en_raise(handler):
                guardado = True
                continue
            if nombres & AMPLIOS and not guardado and not _termina_en_raise(handler):
                malas.append(f"{ruta}:{handler.lineno}")
    return malas


def test_ningun_job_se_traga_el_soft_time_limit() -> None:
    malas: list[str] = []
    for archivo in _archivos():
        ruta = archivo.relative_to(BACKEND).as_posix()
        if ruta in PENDIENTES_DEL_MERGE:
            continue
        malas += _violaciones(archivo.read_text(encoding="utf-8"), ruta)
    assert malas == [], (
        "except Exception sin 'except SoftTimeLimitExceeded: raise' antes: el "
        f"corte de Celery se cuenta como fallo del item y el lote sigue: {malas}"
    )


def test_la_guarda_ve_las_formas_de_escribirlo() -> None:
    sin_guarda = "try:\n    x()\nexcept Exception:\n    pass\n"
    desnudo = "try:\n    x()\nexcept:\n    pass\n"
    con_guarda = (
        "try:\n    x()\nexcept SoftTimeLimitExceeded:\n    raise\n"
        "except Exception:\n    pass\n"
    )
    guarda_despues = (
        "try:\n    x()\nexcept Exception:\n    pass\n"
        "except SoftTimeLimitExceeded:\n    raise\n"
    )
    relanza = "try:\n    x()\nexcept Exception:\n    limpiar()\n    raise\n"
    retry = "try:\n    x()\nexcept Exception as e:\n    raise self.retry(exc=e)\n"
    assert _violaciones(sin_guarda, "a")
    assert _violaciones(desnudo, "a")
    assert _violaciones(con_guarda, "a") == []
    assert _violaciones(guarda_despues, "a")
    assert _violaciones(relanza, "a") == []
    assert _violaciones(retry, "a")
