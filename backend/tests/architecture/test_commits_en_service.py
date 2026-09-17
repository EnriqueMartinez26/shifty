"""El commit vive en el service, no en el repositorio ni en el router (CLAUDE.md §2).

Auditoria B3-06, 2026-09-17. Sintoma: ``staff/repository.py`` commiteaba en
``add_schedule``/``update_schedule``/``delete_schedule``/``update_services`` y
``users/repository.py`` en ``create``/``update``/``soft_delete``; ninguno de los
dos estaba en la lista de deuda declarada. Un router no podia componer dos
operaciones en una transaccion porque el repo cerraba la suya por su cuenta.

Este test es la guarda estatica: cualquier ``commit()`` que vuelva a un repo o
router de estos modulos falla en CI.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

SIN_COMMIT = [
    "modules/staff/repository.py",
    "modules/staff/router.py",
    "modules/users/repository.py",
    "modules/users/router.py",
]


def _commit_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "commit"
    ]


@pytest.mark.parametrize("relative", SIN_COMMIT)
def test_repositorios_y_routers_de_staff_y_users_no_commitean(relative: str) -> None:
    path = BACKEND_ROOT / relative
    lineas = _commit_lines(path)
    assert not lineas, (
        f"{relative} commitea en las lineas {lineas}: el commit es del service "
        "(patron de modules/appointments)."
    )


@pytest.mark.parametrize(
    "relative", ["modules/staff/service.py", "modules/users/service.py"]
)
def test_los_services_de_staff_y_users_son_los_duenos_del_commit(
    relative: str,
) -> None:
    path = BACKEND_ROOT / relative
    assert path.exists(), f"falta {relative}"
    assert _commit_lines(path), f"{relative} no commitea: nadie cierra la transaccion"
