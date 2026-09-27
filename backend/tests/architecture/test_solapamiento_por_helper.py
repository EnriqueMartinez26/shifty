"""Toda consulta de solapamiento pasa por el helper con las dos cotas (F1-13).

2026-09-24, plan de rendimiento (R7-02) y su revision. El solapamiento escrito a
mano -- ``X.starts_at < fin, X.ends_at > inicio`` -- solo acota por arriba sobre
un indice que empieza por ``starts_at`` y recorria toda la historia del
profesional; varias copias ademas no filtraban por tienda. Las consultas pasan
por ``appointment_overlap`` / ``active_block_overlap``
(``modules/appointments/repository.py``), que ponen la tienda y la cota
inferior. Esta guarda estatica falla si un modulo vuelve a escribir
``Appointment.ends_at > ...`` o ``StaffBlock.ends_at > ...`` fuera de ahi.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODELOS = {"Appointment", "StaffBlock"}
COLUMNAS_DE_FIN = {"ends_at", "end_time"}

# El unico lugar donde vive el predicado. ``list_active_overlapping`` arma
# ademas el OR de rangos como FILTRO dentro del sobre que da el helper.
PERMITIDOS = {"modules/appointments/repository.py"}


def _fin_de_modelo(nodo: ast.expr) -> bool:
    return (
        isinstance(nodo, ast.Attribute)
        and nodo.attr in COLUMNAS_DE_FIN
        and isinstance(nodo.value, ast.Name)
        and nodo.value.id in MODELOS
    )


def _solapamientos_a_mano(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        nodo.lineno
        for nodo in ast.walk(tree)
        if isinstance(nodo, ast.Compare)
        and _fin_de_modelo(nodo.left)
        and any(isinstance(op, (ast.Gt, ast.GtE)) for op in nodo.ops)
    ]


def test_ningun_modulo_escribe_el_solapamiento_a_mano() -> None:
    hallazgos = {}
    for path in sorted((BACKEND_ROOT / "modules").rglob("*.py")):
        relativo = path.relative_to(BACKEND_ROOT).as_posix()
        if relativo in PERMITIDOS:
            continue
        if lineas := _solapamientos_a_mano(path):
            hallazgos[relativo] = lineas
    assert not hallazgos, (
        "solapamiento escrito a mano: usar appointment_overlap / "
        f"active_block_overlap de modules/appointments/repository.py: {hallazgos}"
    )
